"""What an experiment runs: a list of runs, read from an experiment file or the command line.

A run is one fuzzer on one benchmark under one compile-time strategy and one
runtime strategy, repeated `trials` times for `max_total_time` seconds each.

An experiment file (run_experiment.py --experiment FILE, YAML or JSON) lists
groups; within a group every fuzzer x benchmark x compile-time strategy x
runtime strategy runs, and the experiment is the union of its groups:

    experiment_name: my_experiment       # optional if --experiment-name is given
    no_superc: true                      # optional, default false
    bug_triaging: [afl-collect]          # optional, default none
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

import json
import sys

import yaml

from color_logger import get_logger

logging = get_logger(__name__)

TOP_KEYS = {"experiment_name", "no_superc", "bug_triaging", "groups", "benchmarks"}
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
