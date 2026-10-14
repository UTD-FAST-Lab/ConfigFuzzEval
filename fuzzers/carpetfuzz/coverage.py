#!/usr/bin/env python3

import os
import subprocess
import shlex
from pathlib import Path
import re

def main():
    out_dir = Path(os.environ.get("OUT", "/fuzzer_output"))
    run_target = os.environ.get("RUN_TARGET")

    if not run_target:
        raise RuntimeError("RUN_TARGET environment variable not set")

    queue_dir = out_dir / "default" / "queue"
    coverage_dir = out_dir / "coverage"
    coverage_dir.mkdir(parents=True, exist_ok=True)

    # -------------------------------
    # Load ranked_stubs.txt into an array
    # -------------------------------
    # run.sh ranks the combinations at the start of each trial and writes the
    # stub file it fuzzed with into the trial's output directory.
    ranked_stubs_file = out_dir / "ranked_stubs.txt"

    if not ranked_stubs_file.is_file():
        raise RuntimeError(f"{ranked_stubs_file} not found")

    # First line is the number of commands; afl-fuzz numbers the commands that
    # follow from 0 (argv:000000 is the first command, not the count line).
    with open(ranked_stubs_file, "r") as f:
        lines = [line.strip() for line in f]
    argv_lines = [line for line in lines[1:int(lines[0]) + 1] if line]

    # -------------------------------
    # Process each queue file
    # -------------------------------
    profraw_files = []

    for seed in sorted(queue_dir.iterdir()):
        if not seed.is_file():
            continue

        # Extract argv number from filename
        match = re.search(r'argv:(\d+)', seed.name)
        # Initial seeds have no argv tag; afl-fuzz runs them with the first command.
        argv_num = int(match.group(1)) if match else 0

        if argv_num >= len(argv_lines):
            print(f"[!] argv {argv_num} out of range, skipping {seed.name}...")
            continue

        stub_cmd = argv_lines[argv_num]

        # Replace the binary with RUN_TARGET
        stub_parts = shlex.split(stub_cmd)
        stub_parts[0] = run_target.split()[0]  # replace binary with RUN_TARGET binary

        # Replace @@ with seed
        cmd_list = [part if part != "@@" else str(seed) for part in stub_parts]

        # profraw file name corresponds to seed name
        profraw_path = coverage_dir / f"{seed.name}.profraw"
        profraw_files.append(str(profraw_path))

        env = os.environ.copy()
        env["LLVM_PROFILE_FILE"] = str(profraw_path)

        print(f"[+] Running target on {seed} -> {profraw_path}")
        try:
            subprocess.run(
                cmd_list,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
                check=False,
            )
        except subprocess.TimeoutExpired:
            print(f"[!] Timeout on {seed}, skipping...")

    # -------------------------------
    # Merge all profraw into a single profdata
    # -------------------------------
    merged_profdata = coverage_dir / "merged.profdata"
    if profraw_files:
        merge_cmd = ["llvm-profdata", "merge", "-sparse", "-o", str(merged_profdata)] + profraw_files
        print(f"[+] Merging {len(profraw_files)} profraw files into {merged_profdata}")
        try:
            subprocess.run(merge_cmd, check=True)
        except subprocess.CalledProcessError as e:
            print(f"[!] Error merging profraw files: {e}")
    else:
        print("[!] No profraw files generated, nothing to merge.")

    # -------------------------------
    # Generate coverage report
    # -------------------------------
    report_json = coverage_dir / "report.json"
    report_txt = coverage_dir / "report.txt"

    try:
        with open(report_json, "w") as f:
            subprocess.run(
                ["llvm-cov", "export", run_target.split()[0], f"-instr-profile={merged_profdata}",
                 # LCOV, like every fuzzer: read by common/report_generation.py and the
                 # SuperC analysis (cfg-analysis/). Unlike the JSON export it stays small
                 # (pcre2: 71 MB of RAM instead of ~56 GB).
                 "-format=lcov"],
                check=True,
                stdout=f
            )
        with open(report_txt, "w") as f:
            subprocess.run(
                ["llvm-cov", "report", run_target.split()[0], f"-instr-profile={merged_profdata}"],
                check=True,
                stdout=f
            )
        print(f"[+] Coverage report generated at {report_txt}")
    except subprocess.CalledProcessError as e:
        print(f"[!] Error generating coverage report: {e}")

    print("[+] Coverage process completed.")
    print(f"[+] Coverage data exported to {coverage_dir}")

if __name__ == "__main__":
    main()
