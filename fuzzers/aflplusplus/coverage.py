#!/usr/bin/env python3
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

    # Merge all profraw into a single profdata file
    merged_profdata = coverage_dir / "merged.profdata"
    if profraw_files:
        merge_cmd = ["llvm-profdata", "merge", "-sparse", "-o", str(merged_profdata)] + profraw_files
        print(f"[+] Merging {len(profraw_files)} profraw files into {merged_profdata}")
        subprocess.run(merge_cmd, check=True)
    else:
        print("[!] No profraw files generated, nothing to merge.")

if __name__ == "__main__":
    main()
