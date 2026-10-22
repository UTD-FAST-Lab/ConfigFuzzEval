#!/usr/bin/env python3

# coverage.py MUST do the following:
# 1. generate .profraw files for each input in the corpus
# 2. merge all .profraw files into a single .profdata file
# 3. store the .profdata file in the coverage directory
# 4. Generate a final report called report.txt in the coverage directory
#
# VAFuzz runs every input under a batch of command-line option configurations, one
# execution per configuration, and takes the union of their coverage
# (common_fuzz_stuff in src/afl-fuzz-run.c). For each queue entry it saves the
# configurations it ran it with as default/queue_argvs/id:<N>_<k>, with "+cov"
# appended to those that found new edges (analyze_feedback_data in
# py-src/z3-solver-generator.py). The argv-instrumented target turns a configuration
# into: program + configuration split on spaces + the run target's own arguments
# (__afl_change_argv in instrumentation/afl-compiler-rt.o.c).
#
# So each queue entry is replayed on the coverage build once per saved configuration,
# in the same argument order. Entries without saved configurations (the seeds, and
# entries found after the last configuration round) run with no options.
# VAFUZZ_COVERAGE_ARGVS=cov replays only the "+cov" configurations.

import os
import shlex
import shutil
import subprocess
import tempfile
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

TIMEOUT = int(os.environ.get("VAFUZZ_COVERAGE_TIMEOUT", "30"))
MERGE_BATCH = 2000  # profraw files merged into merged.profdata at a time


def saved_configs(argv_dir, only_cov):
    """{queue id ("id:000123"): [configuration, ...]} from queue_argvs, without duplicates."""
    configs = defaultdict(list)
    if not argv_dir.is_dir():
        return configs
    for f in sorted(argv_dir.iterdir()):
        if only_cov and not f.name.endswith("+cov"):
            continue
        entry_id = f.name.split("_")[0]
        config = f.read_text(errors="replace").strip()
        if config not in configs[entry_id]:
            configs[entry_id].append(config)
    return configs


def command(run_target, config, seed):
    """The command line of one execution: program, configuration options, target arguments."""
    program, *args = shlex.split(run_target)
    options = [t for t in config.split(" ") if t]  # split like __afl_change_argv's strtok
    if "@@" in args:
        return [program] + options + [str(seed) if a == "@@" else a for a in args], None
    return [program] + options + args, seed.read_bytes()


def merge(profraws, merged_profdata):
    """Merge profraw files into merged.profdata, then delete them."""
    inputs = [str(p) for p in profraws if p.exists()]
    if merged_profdata.exists():
        inputs.append(str(merged_profdata))
    if inputs:
        tmp = merged_profdata.with_suffix(".tmp")
        subprocess.run(["llvm-profdata", "merge", "-sparse", "--failure-mode=warn", "-o", str(tmp)] + inputs, check=True)
        tmp.replace(merged_profdata)
    for p in profraws:
        p.unlink(missing_ok=True)


def main():
    out_dir = Path(os.environ.get("OUT", "/fuzzer_output"))
    run_target = os.environ.get("RUN_TARGET")

    if not run_target:
        raise RuntimeError("RUN_TARGET environment variable not set")

    only_cov = os.environ.get("VAFUZZ_COVERAGE_ARGVS", "all") == "cov"
    queue_dir = out_dir / "default" / "queue"
    coverage_dir = out_dir / "coverage"
    shutil.rmtree(coverage_dir, ignore_errors=True)
    profraw_dir = coverage_dir / "profraw"
    profraw_dir.mkdir(parents=True)
    merged_profdata = coverage_dir / "merged.profdata"

    argv_dir = out_dir / "default" / "queue_argvs"
    configs = saved_configs(argv_dir, only_cov)
    with_configs = set(saved_configs(argv_dir, False)) if only_cov else set(configs)
    runs = []
    seeds = [s for s in sorted(queue_dir.iterdir()) if s.is_file()]
    for seed in seeds:
        entry_id = seed.name.split(",")[0]
        # Entries the fuzzer saved configurations for run only with those (with "cov",
        # only the "+cov" ones, possibly none); the others run with no options.
        for config in configs.get(entry_id, []) if entry_id in with_configs else [""]:
            runs.append((seed, config))
    print(f"[+] {len(seeds)} queue entries, {sum(1 for s in seeds if s.name.split(',')[0] in with_configs)} "
          f"with saved configurations ({'+cov only' if only_cov else 'all'}): {len(runs)} executions", flush=True)

    # Options can make the target write files (-o ..., or output next to the input, like
    # bison): each execution runs in an empty scratch dir of its worker, on a copy of the
    # input, so nothing is written into the fuzzer output.
    workers = max(1, len(os.sched_getaffinity(0)))
    local, scratch = threading.local(), []
    timeouts = 0

    def scratch_dir():
        if not hasattr(local, "dir"):
            local.dir = tempfile.mkdtemp(prefix="vafuzz-cov-")
            scratch.append(local.dir)
        return local.dir

    def execute(n):
        nonlocal timeouts
        seed, config = runs[n]
        work = Path(scratch_dir())
        for f in work.iterdir():
            shutil.rmtree(f) if f.is_dir() and not f.is_symlink() else f.unlink()
        cmd, stdin_data = command(run_target, config, Path(shutil.copy(seed, work / seed.name)))
        env = os.environ.copy()
        env["LLVM_PROFILE_FILE"] = str(profraw_dir / f"{n}.profraw")
        try:
            subprocess.run(cmd, env=env, input=stdin_data, cwd=work,
                           stdin=None if stdin_data is not None else subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=TIMEOUT, check=False)
        except subprocess.TimeoutExpired:
            timeouts += 1

    created = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for start in range(0, len(runs), MERGE_BATCH):
            batch = range(start, min(start + MERGE_BATCH, len(runs)))
            list(pool.map(execute, batch))
            profraws = [profraw_dir / f"{n}.profraw" for n in batch]
            created += sum(p.exists() for p in profraws)
            merge(profraws, merged_profdata)
            print(f"[+] {batch.stop}/{len(runs)} executions run and merged", flush=True)
    for d in scratch:
        shutil.rmtree(d, ignore_errors=True)
    profraw_dir.rmdir()
    print(f"[+] {created}/{len(runs)} profraw files created, {timeouts} timeouts ({TIMEOUT}s)")

    if not merged_profdata.exists():
        print("[!] No profraw files generated, nothing to merge.")
        return

    # Generate coverage report:
    # Run llvm-cov export -> JSON report
    binary = shlex.split(run_target)[0]
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
