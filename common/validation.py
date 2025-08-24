import sys, os
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
    avaibale_fuzzers = [fuzzer.name for fuzzer in os.scandir(fuzzers_dir) if fuzzer.is_dir()]
    
    for potential_fuzzer in fuzzers_selected:
        if potential_fuzzer not in avaibale_fuzzers:
            logging.error(f"Fuzzer {potential_fuzzer} is not available in the project.")
            sys.exit(1)


def validate_ct_strategies(ct_strategies_selected, project_root):
    ct_strategies_dir = os.path.join(project_root, "compiletime")
    available_ct_strategies = [ct_strategy.name for ct_strategy in os.scandir(ct_strategies_dir) if ct_strategy.is_dir()]

    for potential_ct_strategy in ct_strategies_selected:
        if potential_ct_strategy not in available_ct_strategies:
            logging.error(f"Compile-time strategy {potential_ct_strategy} is not available in the project.")
            sys.exit(1)


def validate_benchmarks(benchmarks_selected, project_root):
    benchmarks_dir = os.path.join(project_root, "benchmarks")
    available_benchmarks = [benchmark.name for benchmark in os.scandir(benchmarks_dir) if benchmark.is_dir()]
    
    for potential_benchmark in benchmarks_selected:
        if potential_benchmark not in available_benchmarks:
            logging.error(f"Benchmark {potential_benchmark} is not available in the project.")
            sys.exit(1)
