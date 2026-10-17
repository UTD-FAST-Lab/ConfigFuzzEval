#!/usr/bin/env python3
"""One coverage round of a continuous-mode instance (common/continuous.py).

Runs in the coverage runner image (fbpp/runner-coverage) as root, since the fuzzer's
output is root-owned, with:
  /fuzzer_output   the instance's trial folder (the fuzzer is still writing to it)
  /benchmark       the coverage build of its benchmark copy
  /fuzzer          the fuzzer folder, whose coverage.py is used unchanged
  ROUND            the round number; MIN_AGE: seconds an input must be old to be taken
                   (inputs the fuzzer is still writing wait for the next round; 0 at the end)
  OWNER            uid:gid that gets the results; FUZZER_NAME; CORPUS_DIR (default/queue)

The inputs found since the last round (continuous/processed.txt) are copied into a scratch
folder laid out like a fuzzer output (default/queue, plus default/queue_argvs and the
output's top-level files, which zigzagfuzz, vafuzz and carpetfuzz replay with), the
fuzzer's coverage.py runs on it, and its profile is merged into the cumulative one.
coverage/report.json (LCOV) and coverage/report.txt are then rewritten, by renaming, so
the analyses never read a half-written report. A runtime-strategy instance has one
output folder per configuration it fuzzed (config_<n>, listed in rt_run.jsonl); each gets
its own cumulative profile and reports, and the trial's are their merge.
"""
import json
import os
import shutil
import subprocess
import sys
import time

OUT = "/fuzzer_output"
STATE = os.path.join(OUT, "continuous")
WORK = "/tmp/continuous_round"
SIDE_DIRS = ("queue_argvs",)          # per-input command lines (zigzagfuzz, vafuzz)
MAX_SIDE_FILE = 50 * 2 ** 20


def log(message):
    print(f"[continuous] {message}", flush=True)


def sources(base_target, corpus_dir):
    """[(label, output folder, run target)]: the trial, or each configuration it fuzzed."""
    run_log = os.path.join(OUT, "rt_run.jsonl")
    if not os.path.isfile(run_log):
        return [("", OUT, base_target)]
    configs = json.load(open(os.path.join(OUT, "rt_configs.json")))["configs"]
    binary = base_target.split()[0]
    out = []
    for line in open(run_log):
        if line.strip():
            n = json.loads(line)["config"]
            out.append((f"config_{n}", os.path.join(OUT, f"config_{n}"), " ".join([binary] + configs[n])))
    return out


def read_processed():
    done = set()
    path = os.path.join(STATE, "processed.txt")
    if os.path.isfile(path):
        with open(path) as f:
            done = {line.rstrip("\n") for line in f if line.strip()}
    return done


def new_inputs(label, folder, corpus_dir, done, min_age):
    queue = os.path.join(folder, corpus_dir)
    if not os.path.isdir(queue):
        return queue, []
    now = time.time()
    found = []
    for name in sorted(os.listdir(queue)):
        path = os.path.join(queue, name)
        if name.startswith(".") or not os.path.isfile(path) or f"{label}/{name}" in done:
            continue
        if min_age and now - os.path.getmtime(path) < min_age:
            continue                      # possibly still being written: next round
        found.append(name)
    return queue, found


def stage(folder, queue, names, work, corpus_dir):
    """A fuzzer-output-like folder with only |names| in its queue, and the side files."""
    shutil.rmtree(work, ignore_errors=True)
    dest = os.path.join(work, corpus_dir)
    os.makedirs(dest)
    for name in names:
        shutil.copy2(os.path.join(queue, name), dest)
    parent = os.path.dirname(queue)                      # .../default
    for side in SIDE_DIRS:
        src = os.path.join(parent, side)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(os.path.dirname(dest), side), dirs_exist_ok=True)
    for entry in os.listdir(folder):                     # e.g. carpetfuzz's ranked_stubs.txt
        path = os.path.join(folder, entry)
        if os.path.isfile(path) and os.path.getsize(path) <= MAX_SIDE_FILE:
            shutil.copy2(path, work)


def merge(profiles, dest):
    profiles = [p for p in profiles if p and os.path.isfile(p)]
    if not profiles:
        return False
    tmp = dest + ".tmp"
    subprocess.run(["llvm-profdata", "merge", "-sparse", "-o", tmp, *profiles], check=True)
    os.replace(tmp, dest)
    return True


def export(binary, profdata, coverage_dir):
    os.makedirs(coverage_dir, exist_ok=True)
    for name, args in (("report.json", ["export", binary, f"-instr-profile={profdata}", "-format=lcov"]),
                       ("report.txt", ["report", binary, f"-instr-profile={profdata}"])):
        tmp = os.path.join(coverage_dir, name + ".tmp")
        with open(tmp, "w") as f:
            subprocess.run(["llvm-cov", *args], stdout=f, check=True)
        os.replace(tmp, os.path.join(coverage_dir, name))


def totals(report_txt):
    """{metric: [covered, instrumented]} from the TOTAL row of an llvm-cov report."""
    try:
        row = next(l.split() for l in open(report_txt) if l.startswith("TOTAL"))[1:]
        out = {}
        for metric, (c, m) in zip(("regions", "functions", "lines", "branches"), ((0, 1), (3, 4), (6, 7), (9, 10))):
            out[metric] = [int(row[c]) - int(row[m]), int(row[c])]
        return out
    except (OSError, StopIteration, IndexError, ValueError):
        return None


def chown(owner, paths):
    if not owner:
        return
    for path in paths:
        if os.path.exists(path):
            subprocess.run(["chown", "-R", owner, path], check=False)


def main():
    round_no = int(os.environ.get("ROUND", "0"))
    min_age = int(os.environ.get("MIN_AGE", "30"))
    corpus_dir = os.environ.get("CORPUS_DIR", "default/queue")
    owner = os.environ.get("OWNER")
    base_target = open("/benchmark/run_target.sh").read().strip()
    binary = base_target.split()[0]
    os.makedirs(STATE, exist_ok=True)
    done = read_processed()
    started = time.time()

    record = {"round": round_no, "time": started, "sources": []}
    taken, cumulative = [], []
    for label, folder, target in sources(base_target, corpus_dir):
        queue, names = new_inputs(label or ".", folder, corpus_dir, done, min_age)
        coverage_dir = os.path.join(folder, "coverage")
        profile = os.path.join(coverage_dir, "merged.profdata")
        entry = {"source": label or ".", "new_inputs": len(names),
                 "inputs": len([n for n in os.listdir(queue) if not n.startswith(".")]) if os.path.isdir(queue) else 0}
        if names:
            work = os.path.join(WORK, label or "trial")
            stage(folder, queue, names, work, corpus_dir)
            env = {**os.environ, "OUT": work, "RUN_TARGET": target}
            log(f"{label or 'trial'}: replaying {len(names)} new input(s)")
            result = subprocess.run([sys.executable, "/fuzzer/coverage.py"], env=env)
            round_profile = os.path.join(work, "coverage", "merged.profdata")
            if os.path.isfile(round_profile):
                os.makedirs(coverage_dir, exist_ok=True)
                merge([profile if os.path.isfile(profile) else None, round_profile], profile)
                taken += [f"{label or '.'}/{n}" for n in names]
            else:
                log(f"{label or 'trial'}: coverage.py made no profile (exit code {result.returncode}); "
                    f"its inputs are tried again next round")
                entry["error"] = f"no profile (exit code {result.returncode})"
                names = []
            shutil.rmtree(work, ignore_errors=True)
        if os.path.isfile(profile):
            cumulative.append(profile)
            if label and names:       # a configuration's own reports (statistics: union vs best configuration)
                export(target.split()[0], profile, coverage_dir)
        record["sources"].append(entry)

    trial_coverage = os.path.join(OUT, "coverage")
    trial_profile = os.path.join(trial_coverage, "merged.profdata")
    changed = bool(taken)
    if changed and any(label for label, *_ in sources(base_target, corpus_dir)):
        os.makedirs(trial_coverage, exist_ok=True)
        merge(cumulative, trial_profile)            # the trial: every configuration together
    if changed or (os.path.isfile(trial_profile) and not os.path.isfile(os.path.join(trial_coverage, "report.txt"))):
        export(binary, trial_profile, trial_coverage)

    if taken:
        with open(os.path.join(STATE, "processed.txt"), "a") as f:
            f.write("".join(t + "\n" for t in taken))
    record.update(new_inputs=len(taken), inputs=sum(s["inputs"] for s in record["sources"]),
                  totals=totals(os.path.join(trial_coverage, "report.txt")), seconds=round(time.time() - started, 1))
    with open(os.path.join(STATE, "rounds.jsonl"), "a") as f:
        f.write(json.dumps(record) + "\n")
    chown(owner, [STATE, trial_coverage] + [os.path.join(folder, "coverage") for label, folder, _ in
                                            sources(base_target, corpus_dir) if label])
    log(f"round {round_no}: {len(taken)} new input(s) in {record['seconds']} s; totals {record['totals']}")


if __name__ == "__main__":
    main()
