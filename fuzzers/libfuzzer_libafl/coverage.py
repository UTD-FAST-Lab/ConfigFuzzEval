#!/usr/bin/env python3
# Enhanced coverage.py for libFuzzer: deeply logs environment, LLVM versions, and merge diagnostics.

import os
import subprocess
from pathlib import Path
import shutil

def run_cmd(cmd, check=True, capture_output=True):
    """Run a subprocess command with debug printing."""
    print(f"[DEBUG] Running command: {' '.join(cmd)}")
    try:
        result = subprocess.run(
            cmd,
            check=check,
            text=True,
            capture_output=capture_output
        )
        if capture_output:
            if result.stdout:
                print(f"[DEBUG] stdout:\n{result.stdout}")
            if result.stderr:
                print(f"[DEBUG] stderr:\n{result.stderr}")
        return result
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Command failed: {' '.join(cmd)}")
        print(f"[ERROR] Return code: {e.returncode}")
        if e.stdout:
            print(f"[ERROR] stdout:\n{e.stdout}")
        if e.stderr:
            print(f"[ERROR] stderr:\n{e.stderr}")
        raise

def main():
    out_dir = Path(os.environ.get("OUT", "/fuzzer_output"))
    run_target = os.environ.get("RUN_TARGET")
    if not run_target:
        raise RuntimeError("RUN_TARGET environment variable not set")

    coverage_dir = out_dir / "coverage"
    coverage_dir.mkdir(parents=True, exist_ok=True)

    # Locate the .profraw file
    profraw_path = out_dir / "profraw" / "default.profraw"
    if not profraw_path.exists():
        alt = list(out_dir.rglob("*.profraw"))
        print(f"[!] default.profraw not found. Found {len(alt)} others:")
        for p in alt:
            print(f"    {p} ({p.stat().st_size} bytes)")
        if not alt:
            raise FileNotFoundError("No .profraw files found at all.")
        profraw_path = alt[0]
        print(f"[INFO] Using fallback profraw: {profraw_path}")
    else:
        print(f"[DEBUG] Found profraw: {profraw_path} ({profraw_path.stat().st_size} bytes)")

    # Try inspecting the raw bytes (header)
    try:
        with open(profraw_path, "rb") as f:
            header = f.read(8)
        print(f"[DEBUG] Profraw header bytes: {header.hex()} (first 8 bytes)")
    except Exception as e:
        print(f"[WARN] Could not read profraw header: {e}")

    merged_profdata = coverage_dir / "merged.profdata"
    merge_cmd = ["llvm-profdata-18", "merge", "-sparse", "-o", str(merged_profdata), str(profraw_path)]
    print(f"[DEBUG] === Merging Profraw ===")
    try:
        run_cmd(merge_cmd)
        print(f"[+] Successfully merged into: {merged_profdata}")
    except Exception as e:
        print(f"[!] Merge failed: {e}")
        return

    # Generate coverage
    binary = run_target.split()[0]
    report_json = os.path.join(coverage_dir, "report.json")
    report_txt = os.path.join(coverage_dir, "report.txt")
    
    try:
        with open(report_json, "w") as f:
            subprocess.run(
                ["llvm-cov-18", "export", binary, f"-instr-profile={merged_profdata}"],
                check=True,
                stdout=f
            )
        with open(report_txt, "w") as f:
            subprocess.run(
                ["llvm-cov-18", "report", binary, f"-instr-profile={merged_profdata}"],
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