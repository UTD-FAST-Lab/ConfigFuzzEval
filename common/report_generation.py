import os
import sys
import json
from collections import defaultdict
import argparse
import re
import traceback
from color_logger import get_logger
import pprint
import pandas as pd


logging = get_logger(__name__)


def get_covered_lines(export):
    """
    Return {filename: sorted_list_of_executed_line_numbers} from an llvm-cov export JSON.

    Accepts either a dict (already parsed JSON) or a JSON string.
    Implements the same per-line logic used by LLVM's LineCoverageStats:
      - group segments by line, sorted by column
      - a line is 'mapped' unless it starts a skipped region
      - the line's execution count is the max of:
          * the wrapped segment's count (last segment from the previous line), and
          * counts of non-gap, region-entry segments on this line
      - a line is considered executed iff it is mapped and its computed execution count > 0

    Handles both 5-field and 6-field segment tuples (older vs newer llvm-cov):
      [line, col, count, hasCount, isRegionEntry, (optional) isGapRegion]
    """
    if isinstance(export, str):
        export = json.loads(export)

    results = defaultdict(set)

    for unit in export.get("data", []):
        for f in unit.get("files", []):
            filename = f.get("filename")
            segments = f.get("segments", [])

            # Normalize segments: (line, col, count, hasCount, isRegionEntry, isGapRegion)
            norm = []
            for s in segments:
                if len(s) == 5:
                    line, col, count, hasCount, isRegionEntry = s
                    isGapRegion = False
                else:
                    line, col, count, hasCount, isRegionEntry, isGapRegion = s
                norm.append((int(line), int(col), int(count), bool(hasCount), bool(isRegionEntry), bool(isGapRegion)))

            # Group by line, sort by column
            by_line = defaultdict(list)
            for seg in norm:
                by_line[seg[0]].append(seg)
            for line in by_line:
                by_line[line].sort(key=lambda t: t[1])  # sort by column

            if not by_line:
                continue

            min_line = min(by_line.keys())
            max_line = max(by_line.keys())

            wrapped_segment = None  # last segment from the previous processed line (or earlier)
            for line in range(min_line, max_line + 1):
                segs = by_line.get(line, [])

                # StartOfSkippedRegion: first segment on line has !hasCount and isRegionEntry
                start_of_skipped = bool(segs) and (not segs[0][3]) and segs[0][4]

                # MinRegionCount: number of non-gap, hasCount, region-entry segments
                min_region_count = sum(1 for s in segs if (not s[5]) and s[3] and s[4])

                # Mapped logic (see LLVM): not a skipped start, AND (wrapped hasCount or have any start segments)
                mapped = (not start_of_skipped) and (
                    (wrapped_segment is not None and wrapped_segment[3]) or (min_region_count > 0)
                )

                # also mapped if any region-entry segment on this line has a count
                if any(s[4] and s[3] for s in segs):
                    mapped = True

                if mapped:
                    # ExecutionCount is max of wrapped.count (if any) and region-entry counts (non-gap)
                    exec_count = 0
                    if wrapped_segment is not None:
                        exec_count = wrapped_segment[2]
                    if min_region_count > 0:
                        for s in segs:
                            if (not s[5]) and s[3] and s[4]:  # non-gap, hasCount, region entry
                                if s[2] > exec_count:
                                    exec_count = s[2]

                    if exec_count > 0:
                        results[filename].add(line)

                # After processing the line, update wrapped to the last segment *on this line* if any
                if segs:
                    wrapped_segment = segs[-1]
                # If there were no segments on this line, wrapped_segment remains whatever it was

    # Convert sets to sorted lists
    return {fn: sorted(lines) for fn, lines in results.items()}

# Generate benchmark level reports: Individual and Average

def generate_benchmark_level_reports(path_to_trial_data):
    results = []

    if not os.path.isdir(path_to_trial_data):
        raise FileNotFoundError(
            f"Directory not found: {path_to_trial_data}"
        )

    for entry in sorted(os.listdir(path_to_trial_data)):
        trial_dir = os.path.join(path_to_trial_data, entry)
        if not os.path.isdir(trial_dir):
            continue
        report_path = os.path.join(trial_dir, "coverage", "report.json")
        if not os.path.isfile(report_path):
            continue

        branches_covered = None

        try:
            with open(report_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            items = data.get("data") or []
            if items:
                totals = (items[0].get("totals") or {})
                lines = totals.get("lines") or {}
                branches = totals.get("branches") or {}
                # Branches
                if "count" in branches and "covered" in branches:
                    branches_covered = int(branches.get("covered") or 0)
            # Covered lines list
            covered_lines_ls = get_covered_lines(data)
        except Exception:
            logging.critical(
                f"Failed to read/parse coverage report: {report_path}"
            )
            logging.info("Traceback:")
            logging.info(traceback.format_exc())
            continue

        results.append(
            {
                "trial": entry,
                "lines": {
                    "covered": sum(len(lines) for lines in covered_lines_ls.values()),
                },
                "branches": {
                    "covered": branches_covered,
                },
                "covered_lines_ls": covered_lines_ls
            }
        )
    


    return results




def compare_executed_lines(*dicts):
    """
    Compare N executed-lines dicts of the form {filename: [lines]}.

    Returns:
      {
        "exclusive": [count_for_dict0, count_for_dict1, ...],
        "intersection": count_of_lines_in_all
      }
    """
    if len(dicts) < 2:
        raise ValueError("Need at least two coverage dictionaries")

    # Convert each dict into a set of (filename, line) pairs
    sets = []
    for d in dicts:
        s = {(fn, ln) for fn, lines in d.items() for ln in lines}
        sets.append(s)

    # Exclusive = elements only in that set, not in union of others
    exclusives = []
    for i, s in enumerate(sets):
        others = set().union(*(sets[:i] + sets[i+1:]))
        exclusives.append(len(s - others))

    # Intersection = elements common to all sets
    intersection = set.intersection(*sets)

    return {
        "exclusive": exclusives,
        "intersection": len(intersection)
    }


def reformat_result_dict(data: dict) -> dict:
    """
    Transform a fuzzing coverage dict:
      1) Replace 'lines' -> 'lines_covered' with value data['lines']['covered'].
      2) Replace 'branches' -> 'branches_covered' with value data['branches']['covered'].
      3) Lift/unravel all items under 'covered_lines_ls' to top level,
         then remove that key.
    """
    out = {}

    # Keep existing top-level keys except the ones we will replace
    for k, v in data.items():
        if k not in ("lines", "branches", "covered_lines_ls"):
            out[k] = v

    # 1) lines -> lines_covered
    out["lines_covered"] = data["lines"]["covered"]

    # 2) branches -> branches_covered
    out["branches_covered"] = data["branches"]["covered"]
    out['covered_lines_ls'] = data['covered_lines_ls']

    return out


def results_json_records(data):
    output = []

    for file,lines in data["covered_lines_ls"].items():
        record = {}
        record['trial'] = data['trial']
        record['lines_covered'] = data['lines_covered']
        record['branches_covered'] = data['branches_covered']
        record['file'] = file
        record['covered_lines_ls'] = lines
        output.append(record)   
    
    return output


def records_to_dataframe(raw_results):
    """
    Convert a list of dictionaries (records) into a pandas DataFrame.

    Args:
        records (list): List of dictionaries where each dictionary represents a record.

    Returns:
        pandas.DataFrame: DataFrame containing the data from the records.
    """
    records = []
    for result in raw_results:
        formatted_result = reformat_result_dict(result)
        records += results_json_records(formatted_result)    

    df = pd.DataFrame(records)
    df['trial_split'] = df['trial'].apply(lambda x: x.split('_'))
    df['fuzzer'] = df['trial_split'].apply(lambda x: x[0])
    df['cts'] = df['trial_split'].apply(lambda x: x[2])
    df['benchmark'] = df['trial_split'].apply(lambda x: "_".join(x[3:5]))
    df['bin_no'] = df['trial_split'].apply(lambda x: x[5])
    df['trial_no'] = df['trial_split'].apply(lambda x: x[7])

    # Rearrange the columns in the specified order
    df = df[
        [
            "trial",
            "benchmark",
            "fuzzer",
            "cts",
            "bin_no",
            "trial_no",
            "file",
            "covered_lines_ls",
            "lines_covered",
            "branches_covered",
        ]
    ]

    return df


def average_coverage(res_df):
    avg_df = res_df.groupby(['benchmark', 'bin_no', 'fuzzer', 'cts']).agg({
        'lines_covered': 'mean',
        'branches_covered': 'mean'
    }).reset_index()
    return avg_df

def union_line_coverage(res_df):
    union_df = res_df.groupby(['benchmark', 'fuzzer', 'cts','file']).agg({
        'covered_lines_ls': lambda lists: sorted(set().union(*lists))
    }).reset_index()
    return union_df

def average_coverage_by_case(res_df):
    avg_df = res_df.groupby(['benchmark', 'fuzzer', 'cts','trial_no', 'file']).agg({
        'covered_lines_ls': lambda lists: sorted(set().union(*lists))
    }).reset_index()

    avg_df['num_lines'] = avg_df['covered_lines_ls'].apply(len)
    avg_df = avg_df.groupby(['benchmark', 'fuzzer', 'cts', 'trial_no']).agg({
        'num_lines': 'sum'
    }).reset_index()
    avg_df = avg_df.groupby(['benchmark', 'fuzzer', 'cts']).agg({
        'num_lines': 'mean'
    }).reset_index().rename(columns={'num_lines': 'avg_lines_covered'})
    return avg_df

def group_files_by_case(res_df):
    grouped_benchmark = res_df.groupby(['benchmark'])
    result = {}
    for benchmark, data in grouped_benchmark:
        grouped_fuzz_cts = data.groupby(['fuzzer','cts'])
        result[benchmark[0]] = {}
        for group, data in grouped_fuzz_cts:
            files_dict = dict(zip(data['file'], data['covered_lines_ls']))
            result[benchmark[0]][group] = files_dict
    return result

def main():
    parser = argparse.ArgumentParser(description="Generate fuzzing experiment reports")
    parser.add_argument("path_to_trial_data", help="Path to the trial data directory")
    parser.add_argument("--output-dir", "-o", help="Output directory for CSV reports", default=None)
    args = parser.parse_args()

    path = args.path_to_trial_data
    output_dir = args.output_dir

    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        logging.info(f"Output directory created or exists: {output_dir}")

    individual_results = generate_benchmark_level_reports(path)
    results_df = records_to_dataframe(individual_results)

    temp_df = results_df[
        [
            "trial",
            "benchmark",
            "bin_no",
            "fuzzer",
            "cts",
            "trial_no",
            "file",
        ]
    ]

    benchmark_count = len(results_df['benchmark'].unique())
    trial_count = len(results_df['trial_no'].unique())
    fuzzer_count = len(results_df['fuzzer'].unique())
    cts_count = len(results_df['cts'].unique())
    file_count = results_df.groupby(['benchmark','bin_no','fuzzer','cts','trial_no'])['file'].count()

    print("=" * 80)
    print(f"Summary:")
    print("-" * 80)
    print(f"Benchmarks: {benchmark_count}")
    print(f"Trials: {trial_count}")
    print(f"Fuzzers: {fuzzer_count}")
    print(f"CTS: {cts_count}")
    print("-" * 80)
    print("File Count by Benchmark, Bin, Fuzzer, CTS, and Trial:")
    print("-" * 80)
    print(file_count)
    print("=" * 80)
    print()

    # --- Individual Results DataFrame ---
    print("=" * 80)
    print("Individual Results DataFrame:")
    print("-" * 80)
    print(results_df)
    print("=" * 80)
    print()
    if output_dir:
        results_df.to_csv(os.path.join(output_dir, "individual_results.csv"), index=False)

    # --- Average Coverage DataFrame ---
    print("=" * 80)
    print("Average Coverage DataFrame:")
    print("-" * 80)
    avgs = average_coverage(results_df)
    print(avgs)
    print("=" * 80)
    print()
    if output_dir:
        avgs.to_csv(os.path.join(output_dir, "average_coverage.csv"), index=False)

    # --- Average Coverage by Case DataFrame ---
    print("=" * 80)
    print("Average Coverage by Case DataFrame:")
    print("-" * 80)
    avg_case_df = average_coverage_by_case(results_df)
    print(avg_case_df)
    print("=" * 80)
    print()
    if output_dir:
        avg_case_df.to_csv(os.path.join(output_dir, "average_coverage_by_case.csv"), index=False)

    # --- Unique Files DataFrame ---
    print("=" * 80)
    print("Unique Files DataFrame:")
    print("-" * 80)
    file_df = results_df.groupby(['benchmark', 'bin_no', 'fuzzer', 'cts'])['file'].nunique().reset_index()
    print(file_df)
    print("=" * 80)
    print()
    if output_dir:
        file_df.to_csv(os.path.join(output_dir, "unique_files.csv"), index=False)

    # --- Files Grouped by Case ---
    print("=" * 80)
    print("Files Grouped by Case:")
    print("-" * 80)
    grouped_files = group_files_by_case(results_df)
    for benchmark, files in grouped_files.items():
        print(f"Benchmark: {benchmark}")
        for key, value in files.items():
            print(f"\tGroup: {key}")
            print(f"\tFiles: {str(value)[:50]} ...")
            print("-" * 80)
        
        if len(files) < 2:
            print("\tNot enough groups to compare executed lines.")
            print("-" * 80)
            continue
        print("\tCompare Executed Lines:")
        comparison = compare_executed_lines(*[v for v in files.values()])
        print("\tComparison Result:", comparison)
        print("-" * 80)
        print()
    print("=" * 80)



if __name__ == "__main__":
    main()