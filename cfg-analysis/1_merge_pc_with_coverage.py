#!/usr/bin/env python3
import os
import json
import argparse


def extract_covered_lines_old(cov_json):
    covered = {}
    for data_entry in cov_json.get("data", []):
        for file_entry in data_entry.get("files", []):
            filename = os.path.basename(file_entry["filename"])  # ✅ normalize
            lines = set()
            for seg in file_entry.get("segments", []):
                line_no = seg[0]
                count = seg[2]
                if count > 0:
                    lines.add(line_no)
            covered[filename] = lines
    return covered


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


def parse_pc_tree(node, results=None, parent_pc=""):
    if results is None:
        results = []
    if "StartLine" in node and "EndLine" in node and "PC" in node:
        results.append({
            "StartLine": node["StartLine"],
            "EndLine": node["EndLine"],
            "PC": parent_pc + "&&"+ node["PC"].strip() if parent_pc != "" else node["PC"].strip()
        })
        if parent_pc == "":
             parent_pc = node["PC"].strip() 
        else:
            parent_pc = parent_pc + "&&" + node["PC"].strip() 
    for sub in node.get("Sub", []):
        print("Parent:", parent_pc)
        if isinstance(sub, list):
            for s in sub:
                parse_pc_tree(s, results, parent_pc)
        elif isinstance(sub, dict):
            parse_pc_tree(sub, results, parent_pc)
    return results


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
        pcs = parse_pc_tree(pc_tree)
        base = fname.replace("sourceline_", "").replace(".json", "") + ".c"
        covered = covered_lines.get(base, set())
        if not covered:
            print(f"No coverage info for {base}")
        for entry in pcs:
            line_numbers = set()
            range_covered_lines = 0
            for line in covered:
                if entry["StartLine"] <= line <= entry["EndLine"]:
                    range_covered_lines += 1
                    line_numbers.add(line)

            entry["Lines Covered"] = range_covered_lines
            if range_covered_lines:
                entry["Covered"] = True
            else:
                entry["Covered"] = False
            entry["SourceFile"] = base
            entry["LineNumbers"] = list(line_numbers)
            merged.append(entry)
    return merged


def main():
    parser = argparse.ArgumentParser(description="Merge presence condition tree with LLVM coverage results")
    parser.add_argument("--pc-dir", required=True, help="Directory with sourceline_pc_outputs")
    parser.add_argument("--cov", nargs='+', required=True, help="Format = Name:path, LLVM coverage JSON file (from llvm-cov export)")
    parser.add_argument("--out", required=True, help="Output JSON file")
    args = parser.parse_args()

    # with open(args.cov) as f:
    #     cov_json = json.load(f)
    covered_lines = {}
    
    
    for run in args.cov:
        name, path = run.split(":", 1)
        print(f"Run name: {name}, path: {path}")
        per_run_covered = extract_covered_lines(path)
        
        # Merge per-run coverage into overall covered_lines dict
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
