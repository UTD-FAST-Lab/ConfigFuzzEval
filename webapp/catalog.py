"""What the repository offers to run: fuzzers, benchmarks, strategies and triage tools,
and which fuzzer/benchmark/strategy combinations can run.

The rules mirror common/validation.py (validate_runs) so the form can warn early; the
dry run of common/run_experiment.py stays the final check.
"""
import json
import os


def _dirs(path, ignore=("__pycache__",)):
    if not os.path.isdir(path):
        return []
    return sorted(e.name for e in os.scandir(path) if e.is_dir() and e.name not in ignore
                  and not e.name.startswith("."))


def _json(path):
    try:
        with open(path) as f:
            return {k: v for k, v in json.load(f).items() if not k.startswith("_")}
    except (OSError, ValueError):
        return {}


def load(project_root):
    fuzzers_dir = os.path.join(project_root, "fuzzers")
    benchmarks_dir = os.path.join(project_root, "benchmarks")
    rt_supported = _json(os.path.join(project_root, "runtime", "supported_fuzzers.json"))
    requirements = _json(os.path.join(fuzzers_dir, "benchmark_requirements.json"))

    fuzzers = {}
    for f in _dirs(fuzzers_dir):
        run_sh = os.path.join(fuzzers_dir, f, "run.sh")
        takes_seed_dir = os.path.isfile(run_sh) and "SEED_DIR" in open(run_sh).read()
        fuzzers[f] = {"runtime_strategies": f in rt_supported and takes_seed_dir,
                      "requires": requirements.get(f, [])}

    benchmarks = {}
    for b in _dirs(benchmarks_dir):
        path = os.path.join(benchmarks_dir, b)
        if b.startswith("cts_") or not os.path.isfile(os.path.join(path, "builder.Dockerfile")):
            continue
        files = set()
        for rel in {"ct_grammar.json", "rt_grammar.json", "dict", *(p for r in requirements.values() for p in r)}:
            if os.path.exists(os.path.join(path, rel)):
                files.add(rel)
        seed = os.path.join(path, "seed")
        benchmarks[b] = {"files": sorted(files), "seeds": len(os.listdir(seed)) if os.path.isdir(seed) else 0}

    def strategies(kind):
        # Like validate_ct_strategies / validate_rt_strategies: a strategy is a folder with a strategy.py
        root = os.path.join(project_root, kind)
        return [s for s in _dirs(root) if os.path.isfile(os.path.join(root, s, "strategy.py"))]

    return {
        "fuzzers": fuzzers,
        "benchmarks": benchmarks,
        "compiletime": strategies("compiletime"),
        "runtime": strategies("runtime"),
        "triagers": _dirs(os.path.join(project_root, "bug-triaging")),
    }


def problems(catalog, fuzzer, benchmark, runtime_strategy):
    """Why a run cannot run (empty when it can), as validate_runs would say."""
    out = []
    files = set(catalog["benchmarks"].get(benchmark, {}).get("files", []))
    if "ct_grammar.json" not in files:
        out.append(f"{benchmark} has no ct_grammar.json")
    for rel in catalog["fuzzers"].get(fuzzer, {}).get("requires", []):
        if rel not in files:
            out.append(f"{fuzzer} needs {benchmark}/{rel}")
    if runtime_strategy != "default":
        if not catalog["fuzzers"].get(fuzzer, {}).get("runtime_strategies"):
            out.append(f"{fuzzer} does not support runtime strategies")
        if "rt_grammar.json" not in files:
            out.append(f"{benchmark} has no rt_grammar.json")
    return out
