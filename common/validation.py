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
    available_triagers = [fuzzer.name for fuzzer in os.scandir(fuzzers_dir) if fuzzer.is_dir()]
    
    for potential_fuzzer in fuzzers_selected:
        if potential_fuzzer not in available_triagers:
            logging.error(f"Fuzzer {potential_fuzzer} is not available in the project.")
            sys.exit(1)


def validate_ct_strategies(ct_strategies_selected, project_root):
    ct_strategies_dir = os.path.join(project_root, "compiletime")
    available_ct_strategies = [ct_strategy.name for ct_strategy in os.scandir(ct_strategies_dir) if ct_strategy.is_dir()]

    for potential_ct_strategy in ct_strategies_selected:
        if potential_ct_strategy not in available_ct_strategies:
            logging.error(f"Compile-time strategy {potential_ct_strategy} is not available in the project.")
            sys.exit(1)


def validate_rt_strategies(rt_strategies_selected, fuzzers_selected, benchmarks_selected, project_root):
    rt_strategies_dir = os.path.join(project_root, "runtime")
    available_rt_strategies = [s.name for s in os.scandir(rt_strategies_dir)
                               if s.is_dir() and os.path.exists(os.path.join(s.path, "strategy.py"))]

    for potential_rt_strategy in rt_strategies_selected:
        if potential_rt_strategy not in available_rt_strategies:
            logging.error(f"Runtime strategy {potential_rt_strategy} is not available in the project.")
            sys.exit(1)

    if all(s == "default" for s in rt_strategies_selected):
        return

    with open(os.path.join(rt_strategies_dir, "supported_fuzzers.json")) as f:
        supported = [k for k in json.load(f) if not k.startswith("_")]
    # A listed fuzzer whose run.sh ignores SEED_DIR would restart every configuration
    # from the benchmark's seeds instead of the previous configuration's corpus.
    for fuzzer in supported:
        run_sh = os.path.join(project_root, "fuzzers", fuzzer, "run.sh")
        if fuzzer in fuzzers_selected and "SEED_DIR" not in open(run_sh).read():
            logging.error(f"{run_sh} must take its seeds from ${{SEED_DIR:-/benchmark/seed}} "
                          f"to run with a runtime strategy (runtime/supported_fuzzers.json).")
            sys.exit(1)

    if not any(fuzzer in supported for fuzzer in fuzzers_selected):
        logging.warning(f"No selected fuzzer supports runtime strategies (runtime/supported_fuzzers.json: "
                        f"{supported}); only the default strategy will run.")
        return

    for benchmark in benchmarks_selected:
        if not os.path.exists(os.path.join(project_root, "benchmarks", benchmark, "rt_grammar.json")):
            logging.error(f"Benchmark {benchmark} has no rt_grammar.json, needed by --runtime-strategy.")
            sys.exit(1)


def validate_benchmarks(benchmarks_selected, project_root):
    benchmarks_dir = os.path.join(project_root, "benchmarks")
    available_benchmarks = [benchmark.name for benchmark in os.scandir(benchmarks_dir) if benchmark.is_dir()]
    
    for potential_benchmark in benchmarks_selected:
        if potential_benchmark not in available_benchmarks:
            logging.error(f"Benchmark {potential_benchmark} is not available in the project.")
            sys.exit(1)

def validate_triagers(triagers_selected, project_root):
    btt_dir = os.path.join(project_root, "bug-triaging")
    available_triagers = [triager.name for triager in os.scandir(btt_dir) if triager.is_dir()]
    
    for potential_triager in triagers_selected:
        if potential_triager not in available_triagers:
            logging.error(f"Triaging {potential_triager} is not available in the project.")
            sys.exit(1)