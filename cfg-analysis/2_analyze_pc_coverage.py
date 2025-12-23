#!/usr/bin/env python3
import json
import argparse
from collections import defaultdict

def analyze_pc_coverage(merged_entries):
    summary = defaultdict(lambda: {
        "regions": 0,
        "covered_regions": 0,
        "total_lines": 0,
        "covered_lines": 0,
        "source_files": set()
    })

    for e in merged_entries:
        pc = e["PC"].strip()
        start, end = e["StartLine"], e["EndLine"]
        covered = e.get("Covered", False)
        lines = max(0, end - start + 1)

        s = summary[pc]
        s["regions"] += 1
        s["total_lines"] += lines
        s["source_files"].add(e["SourceFile"])
        if covered:
            s["covered_regions"] += 1
            s["covered_lines"] += lines

    # finalize
    for pc, s in summary.items():
        s["coverage_ratio_regions"] = (
            s["covered_regions"] / s["regions"] if s["regions"] > 0 else 0
        )
        s["coverage_ratio_lines"] = (
            s["covered_lines"] / s["total_lines"] if s["total_lines"] > 0 else 0
        )
        s["source_files"] = list(s["source_files"])

    return summary


def main():
    parser = argparse.ArgumentParser(description="Aggregate coverage results by presence condition")
    parser.add_argument("--merged", required=True, help="Merged PC + coverage JSON (from merge_pc_with_coverage.py)")
    parser.add_argument("--out-json", default="pc_coverage_summary.json", help="Output aggregated JSON file")
    parser.add_argument("--out-csv", default="pc_coverage_summary.csv", help="Output CSV summary file")
    args = parser.parse_args()

    with open(args.merged) as f:
        merged = json.load(f)

    summary = analyze_pc_coverage(merged)

    # Write JSON
    with open(args.out_json, "w") as f:
        json.dump(summary, f, indent=2)

    # Write CSV
    import csv
    with open(args.out_csv, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "PresenceCondition", "Regions", "CoveredRegions",
            "TotalLines", "CoveredLines",
            "CoverageRatioRegions", "CoverageRatioLines", "SourceFiles"
        ])
        for pc, s in summary.items():
            writer.writerow([
                pc.replace("\n", " "),
                s["regions"], s["covered_regions"],
                s["total_lines"], s["covered_lines"],
                f"{s['coverage_ratio_regions']:.2f}",
                f"{s['coverage_ratio_lines']:.2f}",
                ";".join(s["source_files"])
            ])

    print(f"[+] Aggregated {len(summary)} unique presence conditions")
    print(f"[+] Saved JSON: {args.out_json}")
    print(f"[+] Saved CSV:  {args.out_csv}")


if __name__ == "__main__":
    main()