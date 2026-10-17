#!/usr/bin/env python3

# coverage.py MUST do the following:
# 1. generate .profraw files for each input in the corpus
# 2. merge all .profraw files into a single .profdata file
# 3. store the .profdata file in the coverage directory
# 4. Generate a final report called report.txt in the coverage directory

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

# Limits of __afl_change_argv in ZigZagFuzz's afl-compiler-rt.o.c
MAX_CMDLINE_LEN = 100000
MAX_CMDLINE_PAR = 50000

def zigzag_argv(raw_argv, input_path):
    """Rebuild the argument list exactly as the target saw it while fuzzing.

    ZigZagFuzz stores the full command line (target args included) as
    NUL-separated words. write_argv_file() replaces only the first "@@"
    with the input path, and __afl_change_argv() stops at the first empty
    word and turns a lone 0x02 into an empty argument.
    """
    raw_argv = raw_argv.replace(b"@@", os.fsencode(input_path), 1)
    raw_argv = raw_argv[:MAX_CMDLINE_LEN - 2]
    args = []
    for word in raw_argv.split(b"\x00"):
        if not word or len(args) >= MAX_CMDLINE_PAR - 1:
            break
        args.append(b"" if word == b"\x02" else word)
    return args

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
    binary = run_target.split()[0]

    # The target may write files named on its command line (e.g. pcre2test's
    # output file). During fuzzing ZigZagFuzz redirects those writes to
    # /dev/null; here each input runs from a scratch copy so the corpus stays intact.
    scratch_dir = Path(tempfile.mkdtemp(prefix="zzf_cov_"))
    cur_input = scratch_dir / ".cur_input"

    for seed in sorted(queue_dir.iterdir()):
        if not seed.is_file():
            continue

        # addition for zigzag argv: each queue entry has its own argv file
        testcase_id = seed.name.split(",")[0]
        argv_file = argv_dir / testcase_id

        if not argv_file.exists():
            print(f"[!] Warning: Matching argv file not found for: {seed.name}")
            continue

        with open(argv_file, "rb") as f:
            raw_argv = f.read()

        # profraw file name corresponds to the seed name
        profraw_path = coverage_dir / f"{seed.name}.profraw"
        profraw_files.append(str(profraw_path))

        env = os.environ.copy()
        env["LLVM_PROFILE_FILE"] = str(profraw_path)

        shutil.copyfile(seed, cur_input)
        cmd_list = [binary] + zigzag_argv(raw_argv, cur_input)

        print(f"[+] Running target on {seed} -> {profraw_path}")
        try:
            subprocess.run(
                cmd_list,
                env=env,
                cwd=scratch_dir,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
                check=False,
            )
        except subprocess.TimeoutExpired:
            print(f"[!] Timeout on {seed}, skipping...")

    shutil.rmtree(scratch_dir, ignore_errors=True)

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
        # Pass inputs via a file list: large corpora exceed the kernel argv limit.
        # Each line is "weight,path"; the explicit weight keeps commas in AFL names intact.
        input_list = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False)
        input_list.write("".join(f"1,{p}\n" for p in valid_profraw_files))
        input_list.close()
        merge_cmd = ["llvm-profdata", "merge", "-sparse", "-f", input_list.name, "-o", str(merged_profdata)]
        print(f"[+] Merging {len(valid_profraw_files)} profraw files into {merged_profdata}")
        try:
            subprocess.run(merge_cmd, check=True)
        except subprocess.CalledProcessError as e:
            print(f"[!] Error merging profraw files: {e}")
        else:
            # merged.profdata has everything the reports need; the per-input profiles
            # are almost all of a trial's size on disk.
            for f in profraw_files:
                Path(f).unlink(missing_ok=True)
    else:
        print("[!] No valid profraw files generated, nothing to merge.")
    
    # Generate coverage report:
    # Run llvm-cov export -> JSON report
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
