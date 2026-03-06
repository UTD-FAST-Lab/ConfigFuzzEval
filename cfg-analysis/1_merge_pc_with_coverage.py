#!/usr/bin/env python3
import os
import json
import argparse


def extract_covered_lines(cov_file):
    with open(cov_file) as f:
        covered = {}
        lines = set()
        filename = None

        for line in f:
            if line.startswith("SF:"):
                if filename is not None:
                    covered[filename] = lines

                filename = os.path.basename(line.strip().split(":", 1)[1])
                lines = set()

            elif line.startswith("DA:"):
                line_no, exec_count = line.strip().split(":", 1)[1].split(",")
                line_no = int(line_no)
                exec_count = int(exec_count)
                if exec_count > 0:
                    lines.add(line_no)

        if filename is not None:
            covered[filename] = lines

    return covered


def load_pc_file(path):
    with open(path) as f:
        return json.load(f)


def iter_sub_nodes(sub_entries):
    for sub in sub_entries:
        if isinstance(sub, list):
            for item in sub:
                if isinstance(item, dict):
                    yield item
        elif isinstance(sub, dict):
            yield sub


def parse_pc_tree(node, results=None, parent_pc=""):
    if results is None:
        results = []

    start = node.get("StartLine", 0)
    end = node.get("EndLine", -1)
    pc_raw = node.get("PC", "").strip()

    full_pc = f"{parent_pc}&&{pc_raw}" if parent_pc else pc_raw

    if isinstance(start, int) and isinstance(end, int) and end >= start:
        node_lines = set(range(start, end + 1))
    else:
        node_lines = set()

    child_lines = set()
    for child in iter_sub_nodes(node.get("Sub", [])):
        _, child_subtree_lines = parse_pc_tree(child, results, full_pc)
        child_lines.update(child_subtree_lines)

    exclusive_line_numbers = sorted(node_lines - child_lines)
    exclusive_lines = len(exclusive_line_numbers)

    results.append({
        "StartLine": start,
        "EndLine": end,
        "PC": full_pc,
        "ExclusiveLines": exclusive_lines,
        "ExclusiveLineNumbers": exclusive_line_numbers,
    })

    return results, (node_lines | child_lines)


def merge_pc_with_coverage(pc_dir, covered_lines):
    merged = []
    for fname in os.listdir(pc_dir):
        if not fname.endswith(".json"):
            continue

        pc_path = os.path.join(pc_dir, fname)
        try:
            pc_tree = load_pc_file(pc_path)
        except Exception as e:
            print(f"Skipping {fname} ({e})")
            continue

        pcs, _ = parse_pc_tree(pc_tree)
        base = fname.replace("sourceline_", "").replace(".json", "") + ".c"
        covered = covered_lines.get(base, set())

        if not covered:
            print(f"No coverage info for {base}")

        for entry in pcs:
            exclusive_line_numbers = set(entry.get("ExclusiveLineNumbers", []))
            line_numbers = sorted(exclusive_line_numbers.intersection(covered))
            range_covered_lines = len(line_numbers)

            entry["Lines Covered"] = range_covered_lines
            entry["Covered"] = range_covered_lines > 0
            entry["SourceFile"] = base
            entry["LineNumbers"] = line_numbers
            merged.append(entry)

    return merged


def main():
    parser = argparse.ArgumentParser(description="Merge presence condition tree with LLVM coverage results")
    parser.add_argument("--pc-dir", required=True, help="Directory with sourceline_pc_outputs")
    parser.add_argument("--cov", nargs='+', required=True, help="Format = Name:path, LLVM coverage JSON file (from llvm-cov export)")
    parser.add_argument("--out", required=True, help="Output JSON file")
    args = parser.parse_args()

    covered_lines = {}

    for run in args.cov:
        name, path = run.split(":", 1)
        print(f"Run name: {name}, path: {path}")
        per_run_covered = extract_covered_lines(path)

        for fname, lines in per_run_covered.items():
            if fname not in covered_lines:
                covered_lines[fname] = set()
            covered_lines[fname].update(lines)

    merged = merge_pc_with_coverage(args.pc_dir, covered_lines)

    with open(args.out, "w") as f:
        json.dump(merged, f, indent=2)

    print(f"[+] Merged {len(merged)} entries into {args.out}")


if __name__ == "__main__":
    main()
