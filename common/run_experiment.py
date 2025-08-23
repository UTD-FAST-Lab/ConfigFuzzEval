import os
import sys
import yaml
import argparse
from docker_image_builder import build_base_image, build_fuzzer, build_benchmark
import logging

COLOR_CODES = {
    "DEBUG": "\033[36m",    # Cyan
    "INFO": "\033[32m",     # Green
    "WARNING": "\033[33m",  # Yellow
    "ERROR": "\033[31m",    # Red
    "CRITICAL": "\033[41m", # Red background
}
RESET_CODE = "\033[0m"


class ColorFormatter(logging.Formatter):
    def format(self, record):
        levelname = record.levelname
        if levelname in COLOR_CODES:
            record.levelname = f"{COLOR_CODES[levelname]}[{levelname}]{RESET_CODE}"
        else:
            record.levelname = f"[{levelname}]"
        return super().format(record)

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


def validate_benchmarks(benchmarks_selected, project_root):
    benchmarks_dir = os.path.join(project_root, "benchmarks")
    available_benchmarks = [benchmark.name for benchmark in os.scandir(benchmarks_dir) if benchmark.is_dir()]
    
    for potential_benchmark in benchmarks_selected:
        if potential_benchmark not in available_benchmarks:
            logging.error(f"Benchmark {potential_benchmark} is not available in the project.")
            sys.exit(1)


if __name__ == "__main__":
    # Set up logging
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(ColorFormatter("%(levelname)s - %(message)s"))

    logger = logging.getLogger()  # root logger
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    
    logger.info("Starting experiment runner...")
    
    # Process arguments
    parser = argparse.ArgumentParser(description="Run experiments.")
    parser.add_argument("--config", type=str, required=True, help="Path to the configuration file.")
    parser.add_argument("--fuzzers", type=str, nargs='+', required=True, help="List of fuzzers to run.")
    parser.add_argument("--benchmarks", type=str, nargs='+', required=True, help="List of benchmarks to run.")
    parser.add_argument("--compiletime", type=str, nargs='+', required=False, default=["default"], help="Compile time strategies to use.")
    parser.add_argument("--experiment-name", type=str, required=True, help="Name of the experiment.")
    
    args = parser.parse_args()
    
    logging.info("Running experiments with the following parameters:")
    logging.info(f"Configuration file: {args.config}")
    logging.info(f"Fuzzers: {args.fuzzers}")
    logging.info(f"Benchmarks: {args.benchmarks}")
    logging.info(f"Compile time strategies: {args.compiletime}")
    logging.info(f"Experiment name: {args.experiment_name}")
    
    # Read configuration
    with open(args.config, "r") as f:
        config = yaml.safe_load(f)
        
    # Validate configuration
    validate_configuration(config)
    
    # Save all to a state
    experiment_state = {
        "fuzzers": args.fuzzers,
        "benchmarks": args.benchmarks,
        "compiletime": args.compiletime,
        "trials": config["trials"],
        "max_total_time": config["max_total_time"],
        "base_image_path": config["base_image_path"],
        "experiment_filestore": config["experiment_filestore"],
        "report_filestore": config["report_filestore"],
        "project_root": os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    }
    
    # build experiment in filestore
    experiment_filestore = experiment_state["experiment_filestore"]
    report_filestore = experiment_state["report_filestore"]
    
    if not (os.path.exists(experiment_filestore) and os.path.exists(report_filestore)):
        logging.error(f"One or multiple filestores does not exist.")
        os.makedirs(experiment_filestore, exist_ok=True)
        os.makedirs(report_filestore, exist_ok=True)
    
    experiment_name = args.experiment_name
    experiment_path = os.path.join(experiment_filestore, experiment_name)
    report_path = os.path.join(report_filestore, experiment_name)
    
    experiment_state["experiment_path"] = experiment_path
    experiment_state["report_path"] = report_path
    
    if (os.path.exists(experiment_path) or os.path.exists(report_path)):
        logging.error(f"Experiment {experiment_name} already exists in the filestore(s).")
        sys.exit(1)

    os.makedirs(experiment_path, exist_ok=True)
    os.makedirs(report_path, exist_ok=True)
    
    logging.info(f"Experiment directory created at: {experiment_path}")
    logging.info(f"Report directory created at: {report_path}")
    
    # Build base image
    logging.info("Building base image...")
    base_image = experiment_state["base_image_path"]
    project_root = experiment_state["project_root"]
    if(build_base_image(base_image, project_root)):
        logging.error("Failed to build base image.")
        sys.exit(1)
    
    logging.info("Base image built successfully.")
    
    # Validate and build selected fuzzers
    logging.info("Validating fuzzers...")
    validate_fuzzers(experiment_state["fuzzers"], project_root)
    logging.info("Fuzzers validated successfully.")
    logging.info("Building selected fuzzers...")
    built_fuzzers = []
    fuzzer_failures = []
    for fuzzer in experiment_state["fuzzers"]:
        if build_fuzzer(fuzzer, experiment_path, project_root):
            built_fuzzers.append(fuzzer)
        else:
            fuzzer_failures.append(fuzzer)

    if fuzzer_failures:
        logging.warning(f"Fuzzer build failures: {fuzzer_failures}")    
    logging.info(f"Fuzzers built successfully: {built_fuzzers}")

    # validate and build selected benchmarks
    logging.info("Validating benchmarks...")
    validate_benchmarks(experiment_state["benchmarks"], project_root)
    logging.info("Benchmarks validated successfully.")
    logging.info("Building selected benchmarks...")
    built_benchmarks = {}
    benchmark_failures = {}
    for fuzzer in built_fuzzers:
        for benchmark in experiment_state["benchmarks"]:
            logging.info(f"Building target: {benchmark} for fuzzer: {fuzzer}")
            if (build_benchmark(fuzzer, benchmark, experiment_path, project_root)):
                logging.info(f"Successfully built benchmark: {benchmark} for fuzzer: {fuzzer}")
                built_benchmarks[benchmark] = [fuzzer] if benchmark not in built_benchmarks \
                    else built_benchmarks[benchmark].append(fuzzer)
            else:
                logging.error(f"Failed to build benchmark: {benchmark} for fuzzer: {fuzzer}")
                benchmark_failures[benchmark] = [fuzzer] if benchmark not in benchmark_failures \
                    else benchmark_failures[benchmark].append(fuzzer)
    logging.info(f"Benchmark(s) built successfully:")
    for benchmark, fuzzers in built_benchmarks.items():
        logging.info(f"Benchmark: {benchmark}, Fuzzers: {fuzzers}")
    
    if benchmark_failures:
        logging.warning(f"The following benchmarks failed to build:")
        for benchmark, fuzzers in benchmark_failures.items():
            logging.warning(f"Benchmark: {benchmark}, Fuzzers: {fuzzers}")


    # Building coverage binaries
    logging.info("Building coverage binaries...")
    for benchmark in built_benchmarks:
        if(build_benchmark("coverage", benchmark, experiment_path, project_root)):
            logging.info(f"Successfully built coverage binary for benchmark: {benchmark}")
        else:
            logging.error(f"Failed to build coverage binary for benchmark: {benchmark}")
            logging.error("Coverage binaries are essential for result collection. Exiting.")
            sys.exit(1)

    # Run experiments
    # Collect results
    # Print summary


