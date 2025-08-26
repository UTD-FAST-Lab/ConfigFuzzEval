import os
import sys
import yaml
import argparse
from docker_image_builder import build_base_image, build_fuzzer, build_benchmark, run_benchmark, build_runner_image
from color_logger import get_logger
from resource_allocation import allocate_resources
from validation import validate_configuration, validate_fuzzers, validate_benchmarks, validate_ct_strategies
from ct_strategy_applicator import apply_ct_strategy
from concurrent.futures import ThreadPoolExecutor, as_completed


def delete_cts_benchmarks(experiment_state, project_root):
    benchmark_dir = os.path.join(project_root, "benchmarks")
    
    all_cts_benchmarks = set(experiment_state["built_benchmarks"]) | set(experiment_state["benchmark_failures"])
    
    for benchmark in all_cts_benchmarks:
        benchmark_path = os.path.join(benchmark_dir, benchmark)
        if os.path.exists(benchmark_path):
            try:
                # Remove the benchmark directory
                import shutil
                shutil.rmtree(benchmark_path)
                logging.info(f"Removed benchmark directory: {benchmark_path}")
            except Exception as e:
                logging.error(f"Error removing benchmark directory {benchmark_path}: {e}")
        else:
            logging.warning(f"Benchmark directory does not exist, cannot remove: {benchmark_path}")    


def run_experiments(experiment_state):
    built_benchmarks = experiment_state["built_benchmarks"]
    coverage_binaries = experiment_state["coverage_binaries"]
    experiment_path = experiment_state["experiment_path"]
    data_storage = os.path.join(experiment_path, "data")
    os.makedirs(data_storage, exist_ok=True)

    if experiment_state["serial_executions"] == 0:
        core_start = experiment_state["cores_range"][0]
        tasks = []

        # Collect all runs
        for each_built_bench in built_benchmarks:
            for each_fuzzer in built_benchmarks[each_built_bench]:
                for trial_id in range(experiment_state["trials"]):
                    tasks.append((
                        each_fuzzer,
                        each_built_bench,
                        trial_id,
                        core_start
                    ))
                    core_start += 1

        # Run all tasks in parallel
        with ThreadPoolExecutor(max_workers=experiment_state["cores_to_use"]) as executor:
            future_to_task = {
                executor.submit(
                    run_benchmark,
                    fuzzer,
                    benchmark,
                    coverage_binaries[benchmark],
                    experiment_state["report_path"],
                    experiment_state["max_total_time"],
                    experiment_state["trials"],
                    trial_id,
                    experiment_state["experiment_path"],
                    core_id,
                    data_storage,
                    experiment_state["total_memory_needed_gb"]
                ): (fuzzer, benchmark, trial_id, core_id)
                for (fuzzer, benchmark, trial_id, core_id) in tasks
            }

            for future in as_completed(future_to_task):
                fuzzer, benchmark, trial_id, core_id = future_to_task[future]
                try:
                    success = future.result()
                    if success:
                        logging.info(f"[SUCCESS] Completed {fuzzer} on {benchmark}, trial {trial_id}, core {core_id}")
                    else:
                        logging.error(f"[FAILURE] Failed {fuzzer} on {benchmark}, trial {trial_id}, core {core_id}")
                except Exception as e:
                    logging.error(f"[EXCEPTION] {fuzzer} on {benchmark}, trial {trial_id}, core {core_id} -> {e}")
    else:
        # TODO: handle serial executions
        pass

if __name__ == "__main__":
    # Set up logging
    logging = get_logger(__name__)
    
    logging.info("Starting experiment setup...")

    # Process arguments
    parser = argparse.ArgumentParser(description="Run experiments.")
    parser.add_argument("--config", type=str, required=True, help="Path to the configuration file.")
    parser.add_argument("--fuzzers", type=str, nargs='+', required=True, help="List of fuzzers to run.")
    parser.add_argument("--benchmarks", type=str, nargs='+', required=True, help="List of benchmarks to run.")
    parser.add_argument("--compiletime", type=str, nargs='+', required=False, default=["default"], help="Compile time strategies to use.")
    parser.add_argument("--experiment-name", type=str, required=True, help="Name of the experiment.")
    
    args = parser.parse_args()
    
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
        "runner_image_path": config["runner_image_path"],
        "experiment_filestore": config["experiment_filestore"],
        "report_filestore": config["report_filestore"],
        "project_root": os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "cores_to_use": config["cores_to_use"],
        "allow_serial_execution": config["allow_serial_execution"],
        "experiment_memory": config["experiment_memory"]
    }
    
    logging.info("Running experiments with the following parameters:")
    logging.info(f"Configuration file: {args.config}")
    logging.info(f"Fuzzers: {args.fuzzers}")
    logging.info(f"Benchmarks: {args.benchmarks}")
    logging.info(f"Compile time strategies: {args.compiletime}")
    logging.info(f"Experiment name: {args.experiment_name}")
    logging.info(f"Trials: {experiment_state['trials']}")
    logging.info(f"Runtime per trial (seconds): {experiment_state['max_total_time']}")

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
    
    logging.success("Base image built successfully.")
    
    # Build runner image
    logging.info("Building runner image...")
    runner_img_path = experiment_state["runner_image_path"]
    runner_image = f"{runner_img_path}"
    runtime = experiment_state["max_total_time"]
    if build_runner_image(runner_image, project_root, runtime):
        logging.error("Failed to build runner image.")
        sys.exit(1)
        

    # Validate and build selected fuzzers
    logging.info("Validating fuzzers...")
    validate_fuzzers(experiment_state["fuzzers"], project_root)
    logging.info("Fuzzers validated successfully.")
    logging.info("Building selected fuzzers...")
    built_fuzzers = []
    fuzzer_failures = []
    with ThreadPoolExecutor(max_workers=experiment_state["cores_to_use"]) as executor:  # adjust max_workers as needed
        future_to_fuzzer = {
            executor.submit(build_fuzzer, fuzzer, experiment_path, project_root): fuzzer
            for fuzzer in experiment_state["fuzzers"]
        }

        for future in as_completed(future_to_fuzzer):
            fuzzer = future_to_fuzzer[future]
            try:
                success = future.result()
                if success:
                    built_fuzzers.append(fuzzer)
                else:
                    fuzzer_failures.append(fuzzer)
            except Exception as e:
                # if build_fuzzer itself raises
                fuzzer_failures.append(fuzzer)
                logging.error(f"Error building {fuzzer}: {e}")

    if fuzzer_failures:
        logging.warning(f"Fuzzer build failures: {fuzzer_failures}")    
    logging.success(f"Fuzzers built successfully: {built_fuzzers}")

    experiment_state["built_fuzzers"] = built_fuzzers
    experiment_state["fuzzer_failures"] = fuzzer_failures

    # validate selected benchmarks
    logging.info("Validating benchmarks...")
    validate_benchmarks(experiment_state["benchmarks"], project_root)
    logging.info("Benchmarks validated successfully.")
    
    # Validate and build compile-time strategies
    logging.info("Validating compile-time strategies...")
    validate_ct_strategies(experiment_state["compiletime"], project_root)
    logging.info("Compile-time strategies validated successfully.")
    logging.info("Applying selected compile-time strategies...")

    benchmark_mappings = {}

    for strategy in experiment_state["compiletime"]:
        new_benchmark_mapping = apply_ct_strategy(strategy,
                                project_root,
                                experiment_state["benchmarks"])
        benchmark_mappings.update(new_benchmark_mapping)
    
    experiment_state["benchmark_mappings"] = benchmark_mappings
    
    # Build benchmarks
    logging.info("Building selected benchmarks...")
    built_benchmarks = {}
    benchmark_failures = {}
    fuzzer_benchmark_pairs = []

    benchmarks_to_build = []
    for pair in benchmark_mappings:
        benchmarks_to_build.extend(benchmark_mappings[pair])

    # Run benchmark builds in parallel
    cores_available = experiment_state["cores_to_use"]
    with ThreadPoolExecutor(max_workers=cores_available) as executor:  # adjust max_workers as needed
        future_to_pair = {
            executor.submit(build_benchmark, fuzzer, benchmark, experiment_path, project_root): (fuzzer, benchmark)
            for fuzzer in built_fuzzers
            for benchmark in benchmarks_to_build
        }

        for future in as_completed(future_to_pair):
            fuzzer, benchmark = future_to_pair[future]
            try:
                success = future.result()
                if success:
                    logging.info(f"Successfully built benchmark: {benchmark} for fuzzer: {fuzzer}")
                    fuzzer_benchmark_pairs.append(f"{fuzzer}_{benchmark}")

                    if benchmark not in built_benchmarks:
                        built_benchmarks[benchmark] = [fuzzer]
                    else:
                        built_benchmarks[benchmark].append(fuzzer)

                else:
                    logging.error(f"Failed to build benchmark: {benchmark} for fuzzer: {fuzzer}")
                    if benchmark not in benchmark_failures:
                        benchmark_failures[benchmark] = [fuzzer]
                    else:
                        benchmark_failures[benchmark].append(fuzzer)

            except Exception as e:
                logging.error(f"Exception while building {benchmark} for {fuzzer}: {e}")
                if benchmark not in benchmark_failures:
                    benchmark_failures[benchmark] = [fuzzer]
                else:
                    benchmark_failures[benchmark].append(fuzzer)

    logging.success("Benchmark(s) built successfully:")
    for benchmark, fuzzers in built_benchmarks.items():
        logging.success(f"Benchmark: {benchmark}, Fuzzers: {fuzzers}")

    if benchmark_failures:
        logging.warning("The following benchmarks failed to build:")
        for benchmark, fuzzers in benchmark_failures.items():
            logging.warning(f"Benchmark: {benchmark}, Fuzzers: {fuzzers}")

    experiment_state["built_benchmarks"] = built_benchmarks
    experiment_state["benchmark_failures"] = benchmark_failures
    experiment_state["fuzzer_benchmark_pairs"] = fuzzer_benchmark_pairs


    # Build coverage binaries (can also parallelize if needed)
    logging.info("Building coverage binaries...")
    coverage_binaries = {}
    failed_coverage_binaries = []

    with ThreadPoolExecutor(max_workers=experiment_state["cores_to_use"]) as executor:
        future_to_benchmark = {
            executor.submit(build_benchmark, "coverage", benchmark, experiment_path, project_root): benchmark
            for benchmark in built_benchmarks
        }

        for future in as_completed(future_to_benchmark):
            benchmark = future_to_benchmark[future]
            try:
                success = future.result()
                if success:
                    logging.success(f"Successfully built coverage binary for benchmark: {benchmark}")
                    coverage_binaries[benchmark] = f"coverage_{benchmark}"
                else:
                    logging.error(f"Failed to build coverage binary for benchmark: {benchmark}")
                    failed_coverage_binaries.append(benchmark)
            except Exception as e:
                logging.error(f"Exception while building coverage binary for {benchmark}: {e}")
                failed_coverage_binaries.append(benchmark)

    logging.success(f"Coverage binaries built:")
    for binary in coverage_binaries:
        logging.success(f"{binary}")

    if failed_coverage_binaries:
        logging.error(f"Failed coverage binaries:")
        for binary in failed_coverage_binaries:
            logging.error(f"{binary}")

    experiment_state["coverage_binaries"] = coverage_binaries
    experiment_state["failed_coverage_binaries"] = failed_coverage_binaries

    # Resource allocation
    logging.info("Allocating resources for the experiment...")
    experiment_state = allocate_resources(experiment_state)
    logging.success("Resources allocated successfully.")
    logging.debug(f"Experiment state after resource allocation: {experiment_state}")

    # Run experiments
    logging.info("Ready to begin experiments!")
    run_experiments(experiment_state)
    
    

    
    # Collect results
    # Print summary
    
    # Cleanup
    delete_cts_benchmarks(experiment_state, project_root)