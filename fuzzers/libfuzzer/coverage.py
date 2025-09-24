#!/usr/bin/env python3
# coverage.py for libFuzzer: uses the single profraw produced during fuzzing.

import os
import subprocess
from pathlib import Path

def main():
    out_dir = Path(os.environ.get("OUT", "/fuzzer_output"))
    run_target = os.environ.get("RUN_TARGET")
    if not run_target:
        raise RuntimeError("RUN_TARGET environment variable not set")

    coverage_dir = out_dir / "coverage"
    coverage_dir.mkdir(parents=True, exist_ok=True)

    # Debug: List all files in output directory
    print(f"[DEBUG] Output directory: {out_dir}")
    print(f"[DEBUG] Contents of output directory:")
    for item in out_dir.rglob("*"):
        if item.is_file():
            print(f"  {item} ({item.stat().st_size} bytes)")
        elif item.is_dir():
            print(f"  {item}/ (directory)")
    
    # Debug: Check profraw directory specifically
    profraw_dir = out_dir / "profraw"
    if profraw_dir.exists():
        print(f"[DEBUG] Profraw directory contents:")
        for item in profraw_dir.iterdir():
            if item.is_file():
                print(f"  {item} ({item.stat().st_size} bytes)")
            elif item.is_dir():
                print(f"  {item}/ (directory)")
    else:
        print(f"[DEBUG] Profraw directory does not exist: {profraw_dir}")

    # LibFuzzer fuzz run should have written this already
    profraw_path = out_dir / "profraw" / "default.profraw"
    merged_profdata = coverage_dir / "merged.profdata"

    print(f"[DEBUG] Looking for profraw at: {profraw_path}")
    if not profraw_path.exists():
        print(f"[!] Profraw file does not exist at {profraw_path}")
        # Try to find any .profraw files
        profraw_files = list(out_dir.rglob("*.profraw"))
        print(f"[DEBUG] Found {len(profraw_files)} .profraw files:")
        for f in profraw_files:
            print(f"  {f} ({f.stat().st_size} bytes)")
        return
    elif profraw_path.stat().st_size == 0:
        print(f"[!] Profraw file exists but is empty: {profraw_path}")
        return

    print(f"[+] Found profraw: {profraw_path}")

    # Merge into profdata (even if it’s just one file, llvm-profdata still needs merge)
    merge_cmd = ["llvm-profdata-14", "merge", "-sparse", "-o", str(merged_profdata), str(profraw_path)]
    try:
        subprocess.run(merge_cmd, check=True)
        print(f"[+] Merged into {merged_profdata}")
    except subprocess.CalledProcessError as e:
        print(f"[!] Error merging profraw: {e}")
        return
    # Generate coverage reports
    binary = run_target.split()[0]
    report_json = coverage_dir / "report.json"
    report_txt = coverage_dir / "report.txt"
    try:
        with open(report_json, "w") as f:
            subprocess.run(
                ["llvm-cov-14", "export", binary, f"-instr-profile={merged_profdata}"],
                check=True, stdout=f
            )
        with open(report_txt, "w") as f:
            subprocess.run(
                ["llvm-cov", "report", binary, f"-instr-profile={merged_profdata}"],
                check=True, stdout=f
            )
        print(f"[+] Coverage reports generated at {report_txt} and {report_json}")
    except subprocess.CalledProcessError as e:
        print(f"[!] Error generating coverage report: {e}")

if __name__ == "__main__":
    main()
