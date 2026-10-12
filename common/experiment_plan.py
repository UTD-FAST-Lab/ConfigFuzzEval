"""Which runs an experiment does: every (fuzzer, benchmark, compile-time strategy,
runtime strategy) combination, from --groups or from the command-line flags.

A groups file (YAML) lists groups of fuzzers and benchmarks. A group's
compile-time and runtime strategies default to [default]. The optional top-level
"benchmarks" section sets strategies for a benchmark in every group it appears
in, overriding the group's:

    groups:
      - fuzzers: [aflplusplus]
        benchmarks: [xz_xz, bison_bison]
        runtime-strategy: [default, pairwise, random]
      - fuzzers: [vafuzz, zigzagfuzz]
        benchmarks: [xz_xz, pcre2_pcre2test]
    benchmarks:
      xz_xz:
        compiletime: [default, maximum]

Runtime strategies other than default only apply to the fuzzers in
runtime/supported_fuzzers.json; other fuzzers run default only.
"""

import sys

import yaml

from color_logger import get_logger

logging = get_logger(__name__)

GROUP_KEYS = {"fuzzers", "benchmarks", "compiletime", "runtime-strategy"}
STRATEGY_KEYS = {"compiletime", "runtime-strategy"}


def as_list(value, where):
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and value and all(isinstance(v, str) for v in value):
        return value
    logging.error(f"{where} must be a name or a non-empty list of names, got {value!r}")
    sys.exit(1)


def check_keys(entry, allowed, where):
    if not isinstance(entry, dict):
        logging.error(f"{where} must be a mapping, got {entry!r}")
        sys.exit(1)
    unknown = set(entry) - allowed
    if unknown:
        logging.error(f"{where}: unknown key(s) {sorted(unknown)}; allowed: {sorted(allowed)}")
        sys.exit(1)


def load_groups(path):
    """Groups and per-benchmark overrides from a groups file."""
    with open(path) as f:
        plan = yaml.safe_load(f) or {}
    check_keys(plan, {"groups", "benchmarks"}, path)
    if not isinstance(plan.get("groups"), list) or not plan["groups"]:
        logging.error(f"{path}: 'groups' must be a non-empty list")
        sys.exit(1)

    groups = []
    for i, entry in enumerate(plan["groups"]):
        where = f"{path}: group {i + 1}"
        check_keys(entry, GROUP_KEYS, where)
        for key in ("fuzzers", "benchmarks"):
            if key not in entry:
                logging.error(f"{where} has no '{key}'")
                sys.exit(1)
        groups.append({key: as_list(entry.get(key, ["default"]), f"{where} '{key}'") for key in GROUP_KEYS})

    overrides = {}
    for benchmark, entry in (plan.get("benchmarks") or {}).items():
        where = f"{path}: benchmarks: {benchmark}"
        check_keys(entry, STRATEGY_KEYS, where)
        overrides[benchmark] = {key: as_list(value, f"{where} '{key}'") for key, value in entry.items()}
    return groups, overrides


def resolve_runs(groups, overrides, rt_supported_fuzzers):
    """Every run as (fuzzer, benchmark, compile-time strategy, runtime strategy), in order."""
    unused = set(overrides) - {b for group in groups for b in group["benchmarks"]}
    if unused:
        logging.warning(f"Benchmark settings for {sorted(unused)} are not used: no group includes them.")

    runs, warned = [], set()
    for group in groups:
        for benchmark in group["benchmarks"]:
            settings = {**group, **overrides.get(benchmark, {})}
            for fuzzer in group["fuzzers"]:
                rts_list = settings["runtime-strategy"]
                if fuzzer not in rt_supported_fuzzers and any(s != "default" for s in rts_list):
                    if fuzzer not in warned:
                        logging.warning(f"{fuzzer} does not support runtime strategies "
                                        f"(runtime/supported_fuzzers.json); it runs default only.")
                        warned.add(fuzzer)
                    rts_list = ["default"]
                for cts in settings["compiletime"]:
                    for rts in rts_list:
                        run = (fuzzer, benchmark, cts, rts)
                        if run in runs:
                            logging.warning(f"Run {run} is listed more than once; running it once.")
                        else:
                            runs.append(run)
    return runs


def unique(items):
    """Items without duplicates, in order."""
    return list(dict.fromkeys(items))
