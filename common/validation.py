import sys, os, json
from color_logger import get_logger

logging = get_logger(__name__)

def validate_configuration(config):
    if not config:
        logging.error("Configuration file is empty")
        sys.exit(1)
    if not config["trials"]:
        logging.error("Trials is not set in the configuration file")
        sys.exit(1)
    if not config["max_total_time"]:
        logging.error("Max total time is not set in the configuration file")
        sys.exit(1)
    if not config["base_image_path"]:
        logging.error("Base image path is not set in the configuration file")
        sys.exit(1)
    if not config["experiment_filestore"]:
        logging.error("Experiment filestore is not set in the configuration file")
        sys.exit(1)
    if not config["report_filestore"]:
        logging.error("Report filestore is not set in the configuration file")
        sys.exit(1)
    return True


def validate_fuzzers(fuzzers_selected, project_root):
    fuzzers_dir = os.path.join(project_root, "fuzzers")
    # A fuzzer is a folder with the files the framework builds and runs it with.
    available_fuzzers = [fuzzer.name for fuzzer in os.scandir(fuzzers_dir) if fuzzer.is_dir()
                         and os.path.exists(os.path.join(fuzzer.path, "builder.Dockerfile"))
                         and os.path.exists(os.path.join(fuzzer.path, "run.sh"))]

    for potential_fuzzer in fuzzers_selected:
        if potential_fuzzer not in available_fuzzers:
            logging.error(f"Fuzzer {potential_fuzzer} is not available in the project "
                          f"(available: {', '.join(sorted(available_fuzzers))}).")
            sys.exit(1)


def validate_ct_strategies(ct_strategies_selected, project_root):
    ct_strategies_dir = os.path.join(project_root, "compiletime")
    available_ct_strategies = [ct_strategy.name for ct_strategy in os.scandir(ct_strategies_dir)
                               if ct_strategy.is_dir() and os.path.exists(os.path.join(ct_strategy.path, "strategy.py"))]

    for potential_ct_strategy in ct_strategies_selected:
        if potential_ct_strategy not in available_ct_strategies:
            logging.error(f"Compile-time strategy {potential_ct_strategy} is not available in the project "
                          f"(available: {', '.join(sorted(available_ct_strategies))}).")
            sys.exit(1)


def validate_rt_strategies(rt_strategies_selected, project_root):
    rt_strategies_dir = os.path.join(project_root, "runtime")
    available_rt_strategies = [s.name for s in os.scandir(rt_strategies_dir)
                               if s.is_dir() and os.path.exists(os.path.join(s.path, "strategy.py"))]

    for potential_rt_strategy in rt_strategies_selected:
        if potential_rt_strategy not in available_rt_strategies:
            logging.error(f"Runtime strategy {potential_rt_strategy} is not available in the project "
                          f"(available: {', '.join(sorted(available_rt_strategies))}).")
            sys.exit(1)


def validate_runs(runs, project_root):
    """Check that every run can actually run, and stop with every problem listed if not.

    Names are checked first (validate_fuzzers etc.); this checks the combinations:
    - every compile-time strategy needs the benchmark's ct_grammar.json;
    - a non-default runtime strategy needs a fuzzer listed in
      runtime/supported_fuzzers.json whose run.sh takes ${SEED_DIR}, and the
      benchmark's rt_grammar.json;
    - a fuzzer needs the benchmark files listed for it in
      fuzzers/benchmark_requirements.json.
    Nothing is skipped or replaced by a default: a run that cannot run is an error.
    """
    with open(os.path.join(project_root, "runtime", "supported_fuzzers.json")) as f:
        rt_supported = [k for k in json.load(f) if not k.startswith("_")]
    with open(os.path.join(project_root, "fuzzers", "benchmark_requirements.json")) as f:
        requirements = {k: v for k, v in json.load(f).items() if not k.startswith("_")}

    def has(benchmark, path):
        return os.path.exists(os.path.join(project_root, "benchmarks", benchmark, path))

    # (fuzzer, benchmark, reason) -> the runs it affects, so a missing file is reported
    # once, not once per strategy combination.
    problems = {}
    for run in runs:
        fuzzer, benchmark = run["fuzzer"], run["benchmark"]
        reasons = []
        if not has(benchmark, "ct_grammar.json"):
            reasons.append(f"benchmarks/{benchmark}/ct_grammar.json is missing; compile-time strategies need it.")
        for path in requirements.get(fuzzer, []):
            if not has(benchmark, path):
                reasons.append(f"{fuzzer} needs benchmarks/{benchmark}/{path}, which is missing.")
        if run["runtime_strategy"] != "default":
            if fuzzer not in rt_supported:
                reasons.append(f"{fuzzer} does not support runtime strategies; only {', '.join(rt_supported)} "
                               f"do (runtime/supported_fuzzers.json). Use runtime strategy default for {fuzzer}.")
            elif "SEED_DIR" not in open(os.path.join(project_root, "fuzzers", fuzzer, "run.sh")).read():
                reasons.append(f"fuzzers/{fuzzer}/run.sh must take its seeds from ${{SEED_DIR:-/benchmark/seed}} "
                               f"to run with a runtime strategy.")
            if not has(benchmark, "rt_grammar.json"):
                reasons.append(f"benchmarks/{benchmark}/rt_grammar.json is missing; runtime strategies need it.")
        for reason in reasons:
            problems.setdefault((fuzzer, benchmark, reason), []).append(run)

    if problems:
        bad_runs = {(r["fuzzer"], r["benchmark"], r["compiletime"], r["runtime_strategy"])
                    for affected in problems.values() for r in affected}
        logging.error(f"{len(bad_runs)} of the {len(runs)} requested runs cannot run; "
                      f"nothing was built or started:")
        for (fuzzer, benchmark, reason), affected in problems.items():
            combos = ", ".join(dict.fromkeys(f"{r['compiletime']}/{r['runtime_strategy']}" for r in affected))
            origins = "; ".join(dict.fromkeys(r["origin"] for r in affected))
            logging.error(f"  {fuzzer} on {benchmark}: {reason}")
            logging.error(f"      runs (compiletime/runtime strategy): {combos}; from {origins}")
        sys.exit(1)


def validate_benchmarks(benchmarks_selected, project_root):
    benchmarks_dir = os.path.join(project_root, "benchmarks")
    # cts_* folders are an experiment's temporary compile-time copies, not benchmarks.
    available_benchmarks = [benchmark.name for benchmark in os.scandir(benchmarks_dir)
                            if benchmark.is_dir() and not benchmark.name.startswith("cts_")
                            and os.path.exists(os.path.join(benchmark.path, "builder.Dockerfile"))]

    for potential_benchmark in benchmarks_selected:
        if potential_benchmark not in available_benchmarks:
            logging.error(f"Benchmark {potential_benchmark} is not available in the project "
                          f"(available: {', '.join(sorted(available_benchmarks))}).")
            sys.exit(1)

def validate_triagers(triagers_selected, project_root):
    btt_dir = os.path.join(project_root, "bug-triaging")
    available_triagers = [triager.name for triager in os.scandir(btt_dir) if triager.is_dir()]
    
    for potential_triager in triagers_selected:
        if potential_triager not in available_triagers:
            logging.error(f"Triaging {potential_triager} is not available in the project.")
            sys.exit(1)