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
    argv_dir = out_dir / "default" / "queue_argvs"
    coverage_dir = out_dir / "coverage"
    coverage_dir.mkdir(parents=True, exist_ok=True)
    if not queue_dir.exists() or not argv_dir.exists():
        raise FileNotFoundError(f"Queue or queue_argvs directory not found in: {afl_output_dir}")


    profraw_files = []

    for seed in sorted(queue_dir.iterdir()):
        if not seed.is_file():
            continue
        
        # addition for zigzag argv, the argvs need to be cleaned
        testcase_id = seed.name.split(",")[0]
        argv_file = argv_dir / testcase_id

        if not argv_file.exists():
            print(f"[!] Warning: Matching argv file not found for: {seed.name}")
            continue

        with open(argv_file, "rb") as f:
            raw_flags = f.read()

        # Clean argv data (replace null bytes with spaces)
        cleaned_flags = raw_flags.replace(b"\x00", b" ").decode(errors="replace").strip()


        # profraw file name corresponds to the seed name
        profraw_path = coverage_dir / f"{seed.name}.profraw"
        profraw_files.append(str(profraw_path))

        env = os.environ.copy()
        env["LLVM_PROFILE_FILE"] = str(profraw_path)
        
        combined_command = ""
        # Build combined command
        if "@@" in run_target:
            parts = run_target.split("@@", 1)
            combined_command = f"{parts[0]} {cleaned_flags} @@ {parts[1]}".strip()
        else:
            combined_command = f"{run_target} {cleaned_flags}".strip()
            

         # Continue with usual @@ replacement / stdin logic
        if "@@" in combined_command:
            cmd = combined_command.replace("@@", str(seed))
            try:
                # safely split fuzzed argv
                cmd_list = shlex.split(cmd)
            except ValueError:
                print(f"[!] Invalid argv format on {seed}, skipping...")
                continue   # skip this iteration

            # cmd_list = shlex.split(cmd)
            stdin_data = None
        else:
            # cmd_list = shlex.split(combined_command)
            try:
                # safely split fuzzed argv
                cmd_list = shlex.split(combined_command)
            except ValueError:
                print(f"[!] Invalid argv format on {seed}, skipping...")
                continue   # skip this iteration

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

        # debug
    valid_profraw_files = []
    for p in profraw_files:
        try:
            size = os.path.getsize(p)
            print(f"[DEBUG] profraw file: {p} size={size}")
            if size == 0:
                print(f"[!] Warning: {p} is empty")
            else:
                valid_profraw_files.append(p)
        except FileNotFoundError:
            print(f"[!] Warning: profraw file not found, skipping: {p}")
    # end debug
           
# General
    # Merge all profraw into a single profdata file
    merged_profdata = coverage_dir / "merged.profdata"
    if valid_profraw_files:
        merge_cmd = ["llvm-profdata", "merge", "-sparse", "-o", str(merged_profdata)] + valid_profraw_files
        print(f"[+] Merging {len(valid_profraw_files)} profraw files into {merged_profdata}")
        try:
            subprocess.run(merge_cmd, check=True)
        except subprocess.CalledProcessError as e:
            print(f"[!] Error merging profraw files: {e}")
    else:
        print("[!] No valid profraw files generated, nothing to merge.")
    
    # Generate coverage report:
    # Run llvm-cov export -> JSON report
    binary = run_target.split()[0]
    report_json = os.path.join(coverage_dir, "report.json")
    report_txt = os.path.join(coverage_dir, "report.txt")
    
    try:
        with open(report_json, "w") as f:
            subprocess.run(
                ["llvm-cov", "export", binary, f"-instr-profile={merged_profdata}", "-format=lcov"],
                check=True,
                stdout=f
            )
        with open(report_txt, "w") as f:
            subprocess.run(
                ["llvm-cov", "report", binary, f"-instr-profile={merged_profdata}"],
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
