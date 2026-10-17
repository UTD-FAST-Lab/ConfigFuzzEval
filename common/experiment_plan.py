"""What an experiment runs: a list of runs, read from an experiment file or the command line.

A run is one fuzzer on one benchmark under one compile-time strategy and one
runtime strategy, repeated `trials` times for `max_total_time` seconds each.

An experiment file (run_experiment.py --experiment FILE, YAML or JSON) lists
groups; within a group every fuzzer x benchmark x compile-time strategy x
runtime strategy runs, and the experiment is the union of its groups:

    experiment_name: my_experiment       # optional if --experiment-name is given
    no_superc: true                      # optional, default false
    bug_triaging: [afl-collect]          # optional, default none
    cores_to_use: 6                      # optional, default: cores_to_use in --config
    not_applied: {...}                   # optional, ignored: answers saved by the
                                         # interactive setup that are not applied yet
    record: {...}                        # optional, ignored: when it was queued and
                                         # started, its estimated end and stop command
    groups:
      - fuzzers: [vafuzz]
        benchmarks: [xz_xz, bison_bison]
        compiletime: [default]           # optional, default [default]
        runtime_strategy: [default]      # optional, default [default]
        trials: 3                        # optional, default: trials in --config
        max_total_time: 86400            # optional, default: max_total_time in --config
    benchmarks:                          # optional: strategies for a benchmark in every
      xz_xz:                             # group it is in, replacing the group's
        compiletime: [default, maximum]

A benchmarks entry replaces the group's compiletime/runtime_strategy for that
benchmark in every group that runs it; trials and max_total_time come only from the
group or --config.

Every run is checked before anything is built (validation.validate_runs): a run
that cannot run, such as a non-default runtime strategy for a fuzzer that does not
support one, stops the experiment with an error. Nothing is skipped or replaced by
a default.

runtime-strategy is accepted for runtime_strategy, and --groups for --experiment.
The --fuzzers/--benchmarks/--compiletime/--runtime-strategy flags make a single
group with the --config file's trials and max_total_time.
"""

import heapq
import json
import os
import sys
import time

import yaml

from color_logger import get_logger

logging = get_logger(__name__)

TOP_KEYS = {"experiment_name", "no_superc", "bug_triaging", "cores_to_use", "not_applied", "record",
            "groups", "benchmarks"}
GROUP_KEYS = {"fuzzers", "benchmarks", "compiletime", "runtime_strategy", "trials", "max_total_time"}
STRATEGY_KEYS = {"compiletime", "runtime_strategy"}


def fail(message):
    logging.error(message)
    sys.exit(1)


def load_experiment_file(path):
    """Read and check the top level of an experiment file (.json as JSON, anything else as YAML)."""
    try:
        with open(path) as f:
            text = f.read()
    except OSError as e:
        fail(f"Cannot read experiment file {path}: {e}")
    try:
        data = json.loads(text) if path.endswith(".json") else yaml.safe_load(text)
    except (json.JSONDecodeError, yaml.YAMLError) as e:
        fail(f"Cannot parse experiment file {path}: {e}")

    if not isinstance(data, dict):
        fail(f"Experiment file {path} must contain a mapping with a 'groups' list.")
    unknown = sorted(set(data) - TOP_KEYS)
    if unknown:
        fail(f"Experiment file {path}: unknown key(s) {unknown}; allowed: {sorted(TOP_KEYS)}.")
    if not isinstance(data.get("groups"), list) or not data["groups"]:
        fail(f"Experiment file {path} needs a non-empty 'groups' list.")
    if not isinstance(data.get("no_superc", False), bool):
        fail(f"Experiment file {path}: 'no_superc' must be true or false.")
    data["bug_triaging"] = _names(data, "bug_triaging", "the experiment file", default=[], allow_empty=True)
    if "cores_to_use" in data:
        _positive_int(data, "cores_to_use", f"Experiment file {path}", None)
    if not isinstance(data.get("not_applied", {}), dict):
        fail(f"Experiment file {path}: 'not_applied' must be a mapping.")

    benchmarks = data.get("benchmarks") or {}
    if not isinstance(benchmarks, dict):
        fail(f"Experiment file {path}: 'benchmarks' must map benchmark names to their strategies.")
    data["benchmarks"] = {}
    for benchmark, entry in benchmarks.items():
        where = f"Experiment file {path}: benchmarks: {benchmark}"
        entry = _accept_runtime_strategy_alias(entry, where)
        unknown = sorted(set(entry) - STRATEGY_KEYS)
        if unknown:
            fail(f"{where}: unknown key(s) {unknown}; allowed: {sorted(STRATEGY_KEYS)}.")
        data["benchmarks"][benchmark] = {key: _names(entry, key, where) for key in entry}
    return data


def _accept_runtime_strategy_alias(entry, where):
    """entry with runtime-strategy renamed to runtime_strategy."""
    if not isinstance(entry, dict):
        fail(f"{where} must be a mapping.")
    if "runtime-strategy" not in entry:
        return entry
    if "runtime_strategy" in entry:
        fail(f"{where}: give runtime_strategy or runtime-strategy, not both.")
    entry = dict(entry)
    entry["runtime_strategy"] = entry.pop("runtime-strategy")
    return entry


def _names(mapping, key, where, default=None, allow_empty=False):
    """A list of names (a single name is accepted too), without duplicates."""
    value = mapping.get(key, default)
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value) \
            or (not value and not allow_empty):
        fail(f"{where}: '{key}' must be a {'' if allow_empty else 'non-empty '}list of names (got {value!r}).")
    return list(dict.fromkeys(value))


def _positive_int(mapping, key, where, default):
    value = mapping.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        fail(f"{where}: '{key}' must be a positive integer (got {value!r}).")
    return value


def expand_groups(groups, defaults, overrides=None):
    """Groups -> runs: one dict per fuzzer/benchmark/compiletime/runtime_strategy, without duplicates.

    defaults: {"trials", "max_total_time"} from the --config file.
    overrides: {benchmark: {"compiletime"/"runtime_strategy": [...]}}, replacing the
        group's strategies for that benchmark in every group (the file's "benchmarks").
    Each run records where it came from ("origin"), for error messages.
    """
    overrides = overrides or {}
    unused = sorted(set(overrides) - {b for g in groups if isinstance(g, dict)
                                      for b in ([g["benchmarks"]] if isinstance(g.get("benchmarks"), str)
                                                else g.get("benchmarks") or [])})
    if unused:
        fail(f"benchmarks: settings for {', '.join(unused)} would not be used, as no group runs "
             f"{'it' if len(unused) == 1 else 'them'}; add {'it' if len(unused) == 1 else 'them'} "
             f"to a group or remove the settings.")

    runs = {}
    for index, group in enumerate(groups, 1):
        where = f"Group {index}"
        if not isinstance(group, dict):
            fail(f"{where} must be a mapping with at least 'fuzzers' and 'benchmarks'.")
        group = _accept_runtime_strategy_alias(group, where)
        unknown = sorted(set(group) - GROUP_KEYS)
        if unknown:
            fail(f"{where}: unknown key(s) {unknown}; allowed: {sorted(GROUP_KEYS)}.")

        fuzzers = _names(group, "fuzzers", where)
        benchmarks = _names(group, "benchmarks", where)
        compiletime = _names(group, "compiletime", where, default=["default"])
        runtime_strategies = _names(group, "runtime_strategy", where, default=["default"])
        trials = _positive_int(group, "trials", where, defaults["trials"])
        max_total_time = _positive_int(group, "max_total_time", where, defaults["max_total_time"])

        for fuzzer in fuzzers:
            for benchmark in benchmarks:
                override = overrides.get(benchmark, {})
                origin = f"group {index}"
                if override:
                    origin += f", with {' and '.join(sorted(override))} from benchmarks: {benchmark}"
                for ct in override.get("compiletime", compiletime):
                    for rts in override.get("runtime_strategy", runtime_strategies):
                        key = (fuzzer, benchmark, ct, rts)
                        if key in runs:
                            prev = runs[key]
                            if (prev["trials"], prev["max_total_time"]) != (trials, max_total_time):
                                fail(f"{fuzzer} on {benchmark} (compiletime {ct}, runtime strategy {rts}) is in "
                                     f"group {prev['group']} with trials={prev['trials']}, "
                                     f"max_total_time={prev['max_total_time']} and in {where.lower()} with "
                                     f"trials={trials}, max_total_time={max_total_time}; list it once.")
                            continue
                        runs[key] = {"fuzzer": fuzzer, "benchmark": benchmark, "compiletime": ct,
                                     "runtime_strategy": rts, "trials": trials,
                                     "max_total_time": max_total_time, "group": index, "origin": origin}
    return list(runs.values())


def unique(values):
    return list(dict.fromkeys(values))


# --- The saved experiment file: experiments/<name>.yaml ----------------------------

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPERIMENTS_DIR = os.path.join(PROJECT_ROOT, "experiments")
LOGS_DIR = os.path.join(EXPERIMENTS_DIR, "logs")


def saved_experiment_path(name):
    """experiments/<name>.yaml: every experiment, however it was started, is saved here."""
    return os.path.join(EXPERIMENTS_DIR, f"{name}.yaml")


def log_path(name):
    """experiments/logs/<name>.log: the output of every experiment."""
    return os.path.join(LOGS_DIR, f"{name}.log")


def stop_command(name):
    return f"python3 common/jobs.py stop {name}"


class _PlainDumper(yaml.SafeDumper):
    """Writes groups that share a benchmark list in full, without YAML anchors."""

    def ignore_aliases(self, data):
        return True


def _when(value):
    """A time as written in the record: epoch seconds are formatted, a written time is kept."""
    if isinstance(value, str):
        return value
    return time.strftime("%Y-%m-%d %H:%M:%S %Z", time.localtime(value))


def write_experiment_file(path, experiment, record=None):
    """Writes an experiment file: the experiment (without any old record), then its record.

    record: {"queued", "started", "estimated_end"} (epoch seconds) and "stop_command";
    estimated_end gets a comment saying how rough it is. The record is for people
    reading the file; load_experiment_file ignores it, so the file runs again as is.
    """
    experiment = {k: v for k, v in experiment.items() if k != "record"}
    name = experiment.get("experiment_name", "")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("# FuzzBench++ experiment file. Run it again (with a new experiment_name) with\n"
                f"#   python3 common/run_experiment.py --config CONFIG --experiment {os.path.relpath(path, PROJECT_ROOT)}\n"
                "# record is written by run_experiment.py and ignored when the file is read.\n")
        yaml.dump(experiment, f, Dumper=_PlainDumper, sort_keys=False, default_flow_style=None, width=120)
        if record:
            f.write("record:\n")
            for key in ("queued", "started"):
                if record.get(key):
                    f.write(f"  {key}: \"{_when(record[key])}\"\n")
            if record.get("estimated_end"):
                f.write(f"  estimated_end: \"{_when(record['estimated_end'])}\"  # approximate: assumes everything "
                        f"in the run still needs to be built now (see experiment_plan.estimate_seconds)\n")
            f.write(f"  stop_command: \"{record.get('stop_command') or stop_command(name)}\"  "
                    f"# stops it, queued or running (it runs in the background)\n")
            f.write(f"  log: \"{os.path.relpath(log_path(name), PROJECT_ROOT)}\"\n")


def read_record(path):
    """The record of a saved experiment file ({} without one)."""
    try:
        with open(path) as f:
            return (yaml.safe_load(f) or {}).get("record") or {}
    except (OSError, yaml.YAMLError):
        return {}


# --- Estimated duration -------------------------------------------------------

# Rough build times in minutes, from a run on this machine (12 benchmark and 3 coverage
# builds took about 8.5 minutes, 6 at a time) plus uncached fuzzer builds. The estimate
# assumes nothing is cached, so an experiment whose images exist ends earlier.
BUILD_MINUTES = {"base_and_runner": 10, "fuzzer": 15, "benchmark": 3, "coverage": 3}
# Coverage replay and bookkeeping after each trial's fuzzing, and the end of the
# experiment (aggregation, statistics), in minutes.
TRIAL_OVERHEAD_MINUTES = 2
END_MINUTES = 10
# SuperC per benchmark build (copy 0 of each compile-time strategy) when it runs: about a
# minute for objdump's 132 files on 7 cores, more for large benchmarks such as ffmpeg.
SUPERC_MINUTES = 5


def estimate_seconds(runs, copies, config, superc=False):
    """Rough wall-clock time of an experiment from start to end, in seconds.

    runs: from expand_groups; copies: {(compiletime, benchmark): benchmark copies}.
    Builds run build_parallelism at a time, assuming every image must be built; each
    copy of a run's trial fuzzes max_total_time / copies and the trials are packed
    onto cores_to_use cores, longest first.
    """
    parallel = max(1, min(config.get("build_parallelism", 16), config["cores_to_use"]))
    fuzzers = {r["fuzzer"] for r in runs}
    benchmark_builds = sum(copies[(ct, b)] for _, ct, b in {(r["fuzzer"], r["compiletime"], r["benchmark"])
                                                              for r in runs})
    coverage_builds = sum(copies[key] for key in {(r["compiletime"], r["benchmark"]) for r in runs})
    build = 60 * (BUILD_MINUTES["base_and_runner"]
                  + BUILD_MINUTES["fuzzer"] * -(-len(fuzzers) // parallel)
                  + BUILD_MINUTES["benchmark"] * -(-benchmark_builds // parallel)
                  + BUILD_MINUTES["coverage"] * -(-coverage_builds // parallel))
    tasks = []
    for r in runs:
        n = copies[(r["compiletime"], r["benchmark"])]
        tasks += [r["max_total_time"] / n + 60 * TRIAL_OVERHEAD_MINUTES] * (n * r["trials"])
    cores = [0.0] * max(1, config["cores_to_use"])
    for task in sorted(tasks, reverse=True):
        heapq.heapreplace(cores, cores[0] + task)
    analysis = 60 * SUPERC_MINUTES * len({(r["compiletime"], r["benchmark"]) for r in runs}) if superc else 0
    return build + max(cores) + analysis + 60 * END_MINUTES
