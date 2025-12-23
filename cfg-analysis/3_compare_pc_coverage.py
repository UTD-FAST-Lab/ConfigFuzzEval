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
      - lines covered across all regions (approx: if Covered=True -> whole region)
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

        region_lines = max(0, end - start + 1)

        pcs[pc]["regions"] += 1
        pcs[pc]["total_lines"] += region_lines

        if covered:
            pcs[pc]["covered_regions"] += 1
            pcs[pc]["covered_lines"] += region_lines  # approximation

    return pcs


def compare_coverage(pcs_a, pcs_b):
    all_pcs = set(pcs_a.keys()) | set(pcs_b.keys())
    diff = []

    for pc in all_pcs:
        a = pcs_a.get(pc, {"regions": 0, "covered_regions": 0, "total_lines": 0, "covered_lines": 0})
        b = pcs_b.get(pc, {"regions": 0, "covered_regions": 0, "total_lines": 0, "covered_lines": 0})

        cov_a = a["covered_regions"] > 0
        cov_b = b["covered_regions"] > 0

        diff.append({
            "PC": pc,
            "CoveredInA": cov_a,
            "CoveredInB": cov_b,
            "CoveredOnlyInA": cov_a and not cov_b,
            "CoveredOnlyInB": cov_b and not cov_a,
            "RegionsA": a["regions"],
            "RegionsB": b["regions"],
            "TotalLines": max(a["total_lines"], b["total_lines"]),
            "LinesCoveredA": a["covered_lines"],
            "LinesCoveredB": b["covered_lines"]
        })

    return diff


def summarize(diff):
    both = sum(1 for d in diff if d["CoveredInA"] and d["CoveredInB"])
    only_a = sum(1 for d in diff if d["CoveredOnlyInA"])
    only_b = sum(1 for d in diff if d["CoveredOnlyInB"])
    neither = sum(1 for d in diff if not d["CoveredInA"] and not d["CoveredInB"])

    return {
        "total_pcs": len(diff),
        "covered_in_both": both,
        "covered_only_in_A": only_a,
        "covered_only_in_B": only_b,
        "not_covered_any": neither,
        "A_to_B_gain": only_b,
        "B_to_A_loss": only_a
    }


def main():
    parser = argparse.ArgumentParser(description="Compare variability-aware coverage between two fuzzing runs")
    parser.add_argument("--runA", required=True, help="Merged PC coverage JSON for run A")
    parser.add_argument("--runB", required=True, help="Merged PC coverage JSON for run B")
    parser.add_argument("--out-json", default="pc_coverage_comparison.json", help="Output JSON diff file")
    parser.add_argument("--out-csv", default="pc_coverage_comparison.csv", help="Output CSV diff file")
    args = parser.parse_args()

    pcs_a = load_pc_stats(args.runA)
    pcs_b = load_pc_stats(args.runB)

    diff = compare_coverage(pcs_a, pcs_b)
    summary = summarize(diff)

    print(json.dumps(summary, indent=2))

    # Write JSON
    with open(args.out_json, "w") as f:
        json.dump(diff, f, indent=2)

    # Write CSV
    import csv
    with open(args.out_csv, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "PresenceCondition",
            "CoveredInA", "CoveredInB",
            "CoveredOnlyInA", "CoveredOnlyInB",
            "RegionsA", "RegionsB",
            "TotalLines", "LinesCoveredA", "LinesCoveredB"
        ])

        for d in diff:
            writer.writerow([
                d["PC"].replace("\n", " "),
                d["CoveredInA"],
                d["CoveredInB"],
                d["CoveredOnlyInA"],
                d["CoveredOnlyInB"],
                d["RegionsA"],
                d["RegionsB"],
                d["TotalLines"],
                d["LinesCoveredA"],
                d["LinesCoveredB"]
            ])

    print(f"[+] Saved detailed diff to {args.out_json} and {args.out_csv}")


if __name__ == "__main__":
    main()
