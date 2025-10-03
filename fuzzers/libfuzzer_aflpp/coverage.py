#!/usr/bin/env python3

# coverage.py MUST do the following:
# 1. generate .profraw files for each input in the corpus
# 2. merge all .profraw files into a single .profdata file
# 3. store the .profdata file in the coverage directory
# 4. Generate a final report called report.txt in the coverage directory

import os
import subprocess
import shlex
from pathlib import Path

def main():
    out_dir = Path(os.environ.get("OUT", "/fuzzer_output"))
    run_target = os.environ.get("RUN_TARGET")

    if not run_target:
        raise RuntimeError("RUN_TARGET environment variable not set")

    queue_dir = out_dir / "default" / "queue"
    coverage_dir = out_dir / "coverage"
    coverage_dir.mkdir(parents=True, exist_ok=True)

    profraw_files = []

    for seed in sorted(queue_dir.iterdir()):
        if not seed.is_file():
            continue

        # profraw file name corresponds to the seed name
        profraw_path = coverage_dir / f"{seed.name}.profraw"
        profraw_files.append(str(profraw_path))

        env = os.environ.copy()
        env["LLVM_PROFILE_FILE"] = str(profraw_path)

        if "@@" in run_target:
            # Replace @@ with seed path in the run target
            cmd = run_target.replace("@@", str(seed))
            cmd_list = shlex.split(cmd)
            stdin_data = None
        else:
            # Pass seed content through stdin
            cmd_list = shlex.split(run_target)
            with open(seed, "rb") as f:
                stdin_data = f.read()

        print(f"[+] Running target on {seed} -> {profraw_path}")
        try:
            subprocess.run(
                cmd_list,
                env=env,
                input=stdin_data,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
                check=False,
            )
        except subprocess.TimeoutExpired:
            print(f"[!] Timeout on {seed}, skipping...")

# General
    # Merge all profraw into a single profdata file
    merged_profdata = coverage_dir / "merged.profdata"
    if profraw_files:
        merge_cmd = ["llvm-profdata-14", "merge", "-sparse", "-o", str(merged_profdata)] + profraw_files
        print(f"[+] Merging {len(profraw_files)} profraw files into {merged_profdata}")
        try:
            subprocess.run(merge_cmd, check=True)
        except subprocess.CalledProcessError as e:
            print(f"[!] Error merging profraw files: {e}")
    else:
        print("[!] No profraw files generated, nothing to merge.")
    
    # Generate coverage report:
    # Run llvm-cov export -> JSON report
    binary = run_target.split()[0]
    report_json = os.path.join(coverage_dir, "report.json")
    report_txt = os.path.join(coverage_dir, "report.txt")
    
    try:
        with open(report_json, "w") as f:
            subprocess.run(
                ["llvm-cov-14", "export", binary, f"-instr-profile={merged_profdata}"],
                check=True,
                stdout=f
            )
        with open(report_txt, "w") as f:
            subprocess.run(
                ["llvm-cov-14", "report", binary, f"-instr-profile={merged_profdata}"],
                check=True,
                stdout=f
            )
        print(f"[+] Coverage report generated at {report_txt}")
    except subprocess.CalledProcessError as e:
        print(f"[!] Error generating coverage report: {e}")

    print(f"Coverage data exported to report.*")        
    print("[+] Coverage process completed.")

if __name__ == "__main__":
    main()
