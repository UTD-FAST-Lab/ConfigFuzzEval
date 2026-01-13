#!/usr/bin/env python3
import json
import argparse
from collections import defaultdict

def load_pc_stats(path):
    """
    Loads merged PC coverage JSON and aggregates statistics:
      - number of regions per PC
      - whether any region is covered
      - total lines across all regions
      - lines covered across all regions (using "Lines Covered" from entries)
    """

    with open(path) as f:
        entries = json.load(f)

    pcs = defaultdict(lambda: {
        "regions": 0,
        "covered_regions": 0,
        "total_lines": 0,
        "covered_lines": 0
    })

    for e in entries:
        pc = e["PC"].strip()
        start = e["StartLine"]
        end = e["EndLine"]
        covered = e.get("Covered", False)
        covered_lines = e["Lines Covered"]

        region_lines = max(0, end - start + 1)

        pcs[pc]["regions"] += 1
        pcs[pc]["total_lines"] += region_lines

        if covered:
            pcs[pc]["covered_regions"] += 1
            pcs[pc]["covered_lines"] += covered_lines

    return pcs


def compare_coverage_multi(runs_dict):
    """
    Compare coverage across multiple runs.
    
    Args:
        runs_dict: Dictionary mapping run names to their PC stats
    
    Returns:
        List of dictionaries with comparison data for each PC
    """
    run_names = sorted(runs_dict.keys())
    all_pcs = set()
    for pcs in runs_dict.values():
        all_pcs.update(pcs.keys())
    
    diff = []

    for pc in all_pcs:
        entry = {"PC": pc}
        
        # Track coverage status for each run
        covered_in = []
        for run_name in run_names:
            stats = runs_dict[run_name].get(pc, {
                "regions": 0, 
                "covered_regions": 0, 
                "total_lines": 0, 
                "covered_lines": 0
            })
            
            is_covered = stats["covered_regions"] > 0
            entry[f"CoveredIn_{run_name}"] = is_covered
            entry[f"Regions_{run_name}"] = stats["regions"]
            entry[f"LinesCovered_{run_name}"] = stats["covered_lines"]
            
            if is_covered:
                covered_in.append(run_name)
        
        # Calculate total lines (max across all runs)
        entry["TotalLines"] = max(
            runs_dict[run_name].get(pc, {"total_lines": 0})["total_lines"]
            for run_name in run_names
        )
        
        # Add summary fields
        entry["CoveredInRuns"] = covered_in
        entry["NumRunsCovered"] = len(covered_in)
        entry["CoveredInAll"] = len(covered_in) == len(run_names)
        entry["CoveredInNone"] = len(covered_in) == 0
        
        # Unique to specific run(s)
        if len(covered_in) == 1:
            entry["UniquelyIn"] = covered_in[0]
        else:
            entry["UniquelyIn"] = None
            
        diff.append(entry)

    return diff, run_names


def summarize_multi(diff, run_names):
    """Generate summary statistics for multi-run comparison."""
    summary = {
        "total_pcs": len(diff),
        "num_runs": len(run_names),
        "run_names": run_names,
        "covered_in_all": sum(1 for d in diff if d["CoveredInAll"]),
        "covered_in_none": sum(1 for d in diff if d["CoveredInNone"]),
    }
    
    # Per-run statistics
    for run_name in run_names:
        summary[f"covered_in_{run_name}"] = sum(
            1 for d in diff if d[f"CoveredIn_{run_name}"]
        )
        summary[f"unique_to_{run_name}"] = sum(
            1 for d in diff if d.get("UniquelyIn") == run_name
        )
    
    # Coverage distribution
    coverage_dist = defaultdict(int)
    for d in diff:
        coverage_dist[d["NumRunsCovered"]] += 1
    
    summary["coverage_distribution"] = dict(coverage_dist)
    
    return summary


def main():
    parser = argparse.ArgumentParser(
        description="Compare variability-aware coverage across multiple fuzzing runs"
    )
    parser.add_argument(
        "--runs", 
        required=True, 
        nargs='+',
        metavar="NAME:PATH",
        help="Run specifications in format 'name:path' (e.g., runA:data_a.json runB:data_b.json)"
    )
    parser.add_argument(
        "--out-json", 
        default="pc_coverage_comparison.json", 
        help="Output JSON diff file"
    )
    parser.add_argument(
        "--out-csv", 
        default="pc_coverage_comparison.csv", 
        help="Output CSV diff file"
    )
    args = parser.parse_args()

    # Parse run specifications
    runs_dict = {}
    for run_spec in args.runs:
        try:
            name, path = run_spec.split(":", 1)
            runs_dict[name] = load_pc_stats(path)
            print(f"[+] Loaded run '{name}' from {path}")
        except ValueError:
            print(f"[!] Invalid run specification: {run_spec}")
            print("    Expected format: name:path")
            return 1

    if len(runs_dict) < 2:
        print("[!] At least 2 runs are required for comparison")
        return 1

    # Compare coverage
    diff, run_names = compare_coverage_multi(runs_dict)
    summary = summarize_multi(diff, run_names)

    print("\n" + "="*60)
    print("COVERAGE COMPARISON SUMMARY")
    print("="*60)
    print(json.dumps(summary, indent=2))
    print("="*60 + "\n")

    # Write JSON
    output_data = {
        "summary": summary,
        "detailed_comparison": diff
    }
    with open(args.out_json, "w") as f:
        json.dump(output_data, f, indent=2)

    # Write CSV
    import csv
    with open(args.out_csv, "w", newline="") as f:
        writer = csv.writer(f)
        
        # Build header
        header = ["PresenceCondition", "TotalLines", "NumRunsCovered", "UniquelyIn"]
        for run_name in run_names:
            header.extend([
                f"CoveredIn_{run_name}",
                f"Regions_{run_name}",
                f"LinesCovered_{run_name}"
            ])
        writer.writerow(header)

        # Write data rows
        for d in diff:
            row = [
                d["PC"].replace("\n", " "),
                d["TotalLines"],
                d["NumRunsCovered"],
                d.get("UniquelyIn", "")
            ]
            for run_name in run_names:
                row.extend([
                    d[f"CoveredIn_{run_name}"],
                    d[f"Regions_{run_name}"],
                    d[f"LinesCovered_{run_name}"]
                ])
            writer.writerow(row)

    print(f"[+] Saved detailed diff to {args.out_json} and {args.out_csv}")
    return 0


if __name__ == "__main__":
    exit(main())
