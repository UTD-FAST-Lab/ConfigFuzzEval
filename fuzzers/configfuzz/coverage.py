#!/usr/bin/env python3

# Replays the queue on the coverage binary. Each ConfigFuzz input starts with
# option bytes, so ConfigFuzz's printer (generated from the benchmark's grammar)
# decodes every input into the command line it ran with: it writes the data part to
# /dev/shm/optfuzzer.<pid> and prints the arguments, one per line.

import json
import os
import subprocess
from pathlib import Path


def main():
    out_dir = Path(os.environ.get("OUT", "/fuzzer_output"))
    run_target = os.environ.get("RUN_TARGET")

    if not run_target:
        raise RuntimeError("RUN_TARGET environment variable not set")

    target_binary = run_target.split()[0]
    queue_dir = out_dir / "default" / "queue"
    coverage_dir = out_dir / "coverage"
    coverage_dir.mkdir(parents=True, exist_ok=True)

    # -------------------------------
    # Build ConfigFuzz's printer for this benchmark
    # -------------------------------
    grammar_file = Path(target_binary).parent / "rt_grammar.json"
    with open(grammar_file) as f:
        uses_stdin = "$STDIN" in json.load(f)["cmdline"]

    work = Path("/tmp/configfuzz")
    work.mkdir(parents=True, exist_ok=True)
    printer_src = work / "printer.c"
    printer = work / "printer"
    with open(printer_src, "w") as f:
        subprocess.run(["python3", "/fuzzer/make_stub.py", "printer", str(grammar_file)], stdout=f, check=True)
    subprocess.run(["clang", "-O2", "-w", "-o", str(printer), str(printer_src), "-lm"], check=True)

    # -------------------------------
    # Process each queue file
    # -------------------------------
    profraw_files = []

    for seed in sorted(queue_dir.iterdir()):
        if not seed.is_file():
            continue

        decoded = subprocess.run([str(printer), str(seed)], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        args = decoded.stdout.decode(errors="surrogateescape").splitlines()
        # The printer's data file; the only one, as they are removed after each input.
        data_file = next(Path("/dev/shm").glob("optfuzzer.*"), None)
        if decoded.returncode != 0 or not args:
            # Conflicting or unmet dependent options: the stub returns no command
            # line, so the target crashes and the input is not a valid queue entry.
            print(f"[!] Cannot decode {seed.name}, skipping...")
            for f in Path("/dev/shm").glob("optfuzzer.*"):
                f.unlink()
            continue

        cmd_list = [target_binary] + args[1:]

        # profraw file name corresponds to seed name
        profraw_path = coverage_dir / f"{seed.name}.profraw"
        profraw_files.append(str(profraw_path))

        env = os.environ.copy()
        env["LLVM_PROFILE_FILE"] = str(profraw_path)

        print(f"[+] Running target on {seed} -> {profraw_path}")
        stdin_file = open(data_file, "rb") if uses_stdin and data_file else subprocess.DEVNULL
        try:
            subprocess.run(
                cmd_list,
                env=env,
                stdin=stdin_file,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
                check=False,
            )
        except subprocess.TimeoutExpired:
            print(f"[!] Timeout on {seed}, skipping...")
        finally:
            if stdin_file is not subprocess.DEVNULL:
                stdin_file.close()
            for f in Path("/dev/shm").glob("optfuzzer.*"):
                f.unlink()

    # -------------------------------
    # Merge all profraw into a single profdata
    # -------------------------------
    existing_profraw_files = [f for f in profraw_files if Path(f).exists()]
    print(f"[+] {len(existing_profraw_files)}/{len(profraw_files)} profraw files successfully created")

    merged_profdata = coverage_dir / "merged.profdata"
    if existing_profraw_files:
        merge_cmd = ["llvm-profdata", "merge", "-sparse", "-o", str(merged_profdata)] + existing_profraw_files
        print(f"[+] Merging {len(existing_profraw_files)} profraw files into {merged_profdata}")
        try:
            subprocess.run(merge_cmd, check=True)
        except subprocess.CalledProcessError as e:
            print(f"[!] Error merging profraw files: {e}")
            return
    else:
        print("[!] No profraw files generated, nothing to merge.")
        return

    # -------------------------------
    # Generate coverage report
    # -------------------------------
    report_json = coverage_dir / "report.json"
    report_txt = coverage_dir / "report.txt"

    try:
        with open(report_json, "w") as f:
            subprocess.run(
                ["llvm-cov", "export", target_binary, f"-instr-profile={merged_profdata}",
                 # LCOV, like every fuzzer: read by common/report_generation.py and the
                 # SuperC analysis (cfg-analysis/). Unlike the JSON export it stays small
                 # (pcre2: 71 MB of RAM instead of ~56 GB).
                 "-format=lcov"],
                check=True,
                stdout=f
            )
        with open(report_txt, "w") as f:
            subprocess.run(
                ["llvm-cov", "report", target_binary, f"-instr-profile={merged_profdata}"],
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
