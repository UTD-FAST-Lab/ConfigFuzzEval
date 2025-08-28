import os
import sys
import json
from collections import defaultdict
import argparse
import re
import traceback
from color_logger import get_logger
import pprint


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




    # Compute averages across trials for the same base (strip trailing
    # _trial_N)
    averages = {}
    groups = {}
    for r in results:
        trial_name = r["trial"]
        base = re.sub(r"_trial_\d+$", "", trial_name)
        groups.setdefault(base, []).append(r)

    for base, items in groups.items():
        # Filter only items with valid integer counts
        valid_lines = [
            it for it in items
            if isinstance(it["lines"].get("covered"), int)
            and isinstance(it["lines"].get("total"), int)
        ]
        valid_branches = [
            it for it in items
            if isinstance(it["branches"].get("covered"), int)
            and isinstance(it["branches"].get("total"), int)
        ]

        def _avg(values):
            if not values:
                return None
            return sum(values) / float(len(values))

        line_cov_avg = _avg([it["lines"]["covered"] for it in valid_lines])
        line_tot_avg = _avg([it["lines"]["total"] for it in valid_lines])
        br_cov_avg = _avg([it["branches"]["covered"] for it in valid_branches])
        br_tot_avg = _avg([it["branches"]["total"] for it in valid_branches])
        averages[base] = {
            "trials": len(items),
            "lines": {
                "covered_avg": line_cov_avg,
                "total_avg": line_tot_avg,
            },
            "branches": {
                "covered_avg": br_cov_avg,
                "total_avg": br_tot_avg,
            },
        }
    return averages

    # Print averages table


def group_and_print(data):
    grouped = defaultdict(lambda: defaultdict(list))

    for entry in data:
        trial_name = entry['trial']
        parts = trial_name.split("_", 1)
        fuzzer, rest = parts[0], parts[1]

        # only keep trial id (e.g., "trial_0")
        trial_id = "_".join(trial_name.split("_")[-2:])

        simplified = {
            "trial": trial_id,
            "lines": entry["lines"],
            "branches": entry["branches"],
        }

        grouped[rest][fuzzer].append(simplified)

    # ---- printing with averages ----
    for strat_target, fuzzers in grouped.items():
        print(f"\n=== {strat_target} ===")
        for fuzzer, trials in fuzzers.items():
            print(f"  Fuzzer: {fuzzer}")
            covered_lines = covered_branches = 0

            for t in trials:
                lc = t["lines"]["covered"]
                bc = t["branches"]["covered"]

                print(f"    {t['trial']}: "
                      f"lines {lc}, branches {bc}")

                covered_lines += lc
                covered_branches += bc

            # compute averages (just raw averages of covered counts)
            n = len(trials)
            avg_line_cov = covered_lines / n if n else 0
            avg_branch_cov = covered_branches / n if n else 0

            print(f"    -> Avg line coverage: {avg_line_cov:.2f}")
            print(f"    -> Avg branch coverage: {avg_branch_cov:.2f}")


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


def main():
    if len(sys.argv) < 2:
        print("Usage: python report_generation.py <path_to_trial_data>")
        sys.exit(1)
    path = sys.argv[1]
    
    # with open(path, "r", encoding="utf-8") as f:
    #     data = json.load(f)

    # res = get_covered_lines(data)
    # tot_lines = sum(len(lines) for lines in res.values())
    # print(tot_lines)
    # path2 = sys.argv[2]
    
    # with open(path2, "r", encoding="utf-8") as f:
    #     data2 = json.load(f)
        
    # res2 = get_covered_lines(data2)
    # tot_lines2 = sum(len(lines) for lines in res2.values())
    # print(tot_lines2)
    
    # comp = compare_executed_lines(res, res2)
    # print(comp)
    individual_results = generate_benchmark_level_reports(path)
    print(individual_results)
    # res = group_by_target(individual_results)
    # group_and_print(individual_results)
    
    # averages = compute_averages(individual_results)
    # # print("Computed Averages:")
    # # print(averages)
    # target_res = group_by_target(averages)
    
    
    
    
    
    # print_averages(averages)


if __name__ == "__main__":
    main()