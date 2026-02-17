import os
import sys
import yaml
import argparse
from docker_image_builder import build_base_image, build_fuzzer,build_bug_triager, build_benchmark, run_benchmark,run_triaging, build_runner_image, build_superc, run_superc
from color_logger import get_logger
from resource_allocation import allocate_resources
from validation import validate_configuration, validate_fuzzers, validate_benchmarks, validate_ct_strategies, validate_triagers
from ct_strategy_applicator import apply_ct_strategy
from concurrent.futures import ThreadPoolExecutor, as_completed
import pprint
import itertools
import pickle


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

    # --- Write seed info ---
    config_file = os.path.join(data_storage, "ct_seed.txt")
    random_seed = experiment_state["random_seed"]
    with open(config_file, "w") as f:
        f.write(f"# random_seed={random_seed if random_seed is not None else 'None'}\n")

    core_range = experiment_state["cores_range"]
    core_start = core_range[0]
    core_end = core_range[1]
    max_workers = core_end - core_start + 1
    cores = [core for core in range(core_start, core_end + 1)]
    logging.info(f"Core range: {core_range}, using up to {max_workers} workers")

    # --- Collect tasks ---
    tasks = []
    for benchmark in built_benchmarks:
        tot_cts_count = experiment_state["tot_cts"].get(benchmark, 1)
        for fuzzer in built_benchmarks[benchmark]:
            for trial_id in range(experiment_state["trials"]):
                tasks.append((fuzzer, benchmark, trial_id, tot_cts_count))

    # --- Initialize executor ---
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        core_cycle = itertools.cycle(cores)  # Round-robin assignment of cores
        running = {}  # Map of futures → (task, core_id)

        # Start initial batch
        for _ in range(min(max_workers, len(tasks))):
            fuzzer, benchmark, trial_id, tot_cts_count = tasks.pop(0)
            core_id = next(core_cycle)
            future = executor.submit(
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
                experiment_state["total_memory_needed_gb"],
                tot_cts_count
            )
            running[future] = (fuzzer, benchmark, trial_id, core_id, tot_cts_count)
            logging.info(f"[START] {fuzzer} on {benchmark}, trial {trial_id}, core {core_id}")

        # As tasks finish, schedule new ones on the freed core
        while running:
            for finished_future in as_completed(list(running.keys()), timeout=None):
                fuzzer, benchmark, trial_id, core_id, tot_cts_count = running.pop(finished_future)
                try:
                    success = finished_future.result()
                    if success:
                        logging.info(f"[SUCCESS] {fuzzer} on {benchmark}, trial {trial_id}, core {core_id}")
                    else:
                        logging.error(f"[FAILURE] {fuzzer} on {benchmark}, trial {trial_id}, core {core_id}")
                except Exception as e:
                    logging.error(f"[EXCEPTION] {fuzzer} on {benchmark}, trial {trial_id}, core {core_id} -> {e}")

                # Launch next task (reuse freed core)
                if tasks:
                    next_fuzzer, next_bench, next_trial, next_tot_cts = tasks.pop(0)
                    new_future = executor.submit(
                        run_benchmark,
                        next_fuzzer,
                        next_bench,
                        coverage_binaries[next_bench],
                        experiment_state["report_path"],
                        experiment_state["max_total_time"],
                        experiment_state["trials"],
                        next_trial,
                        experiment_state["experiment_path"],
                        core_id,  # reuse same core
                        data_storage,
                        experiment_state["total_memory_needed_gb"],
                        next_tot_cts
                    )
                    running[new_future] = (next_fuzzer, next_bench, next_trial, core_id, next_tot_cts)
                    logging.info(f"[START] {next_fuzzer} on {next_bench}, trial {next_trial}, core {core_id}")

                # Break after processing one finished future
                break


def run_superc_on_experiments(experiment_state, logging=None):
    built_benchmarks = experiment_state["built_benchmarks"]
    experiment_path = experiment_state["experiment_path"]
    data_storage = os.path.join(experiment_path, "data")
    os.makedirs(data_storage, exist_ok=True)

    core_range = experiment_state["cores_range"]
    core_start = core_range[0]
    core_end = core_range[1]
    max_workers = core_end - core_start + 1
    cores = [core for core in range(core_start, core_end + 1)]
    logging.info(f"Core range: {core_range}, using up to {max_workers} workers for SuperC analysis")

    # --- Collect tasks ---
    tasks = []
    for benchmark in built_benchmarks:
        tot_cts_count = experiment_state["tot_cts"].get(benchmark, 1)
        for fuzzer in built_benchmarks[benchmark]:
            for trial_id in range(experiment_state["trials"]):
                tasks.append((fuzzer, benchmark, trial_id, tot_cts_count))

    # --- Initialize executor ---
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        core_cycle = itertools.cycle(cores)  # Round-robin assignment of cores
        running = {}  # Map of futures → (task, core_id)

        # Start initial batch
        for _ in range(min(max_workers, len(tasks))):
            fuzzer, benchmark, trial_id, tot_cts_count = tasks.pop(0)
            core_id = next(core_cycle)
            future = executor.submit(
                run_superc,
                fuzzer,
                benchmark,
                trial_id,
                experiment_state["experiment_path"],
                core_id,
                data_storage,
                experiment_state["total_memory_needed_gb"]
            )
            running[future] = (fuzzer, benchmark, trial_id, core_id, tot_cts_count)
            logging.info(f"[START] SuperC analysis: {fuzzer} on {benchmark}, trial {trial_id}, core {core_id}")

        # As tasks finish, schedule new ones on the freed core
        while running:
            for finished_future in as_completed(list(running.keys()), timeout=None):
                fuzzer, benchmark, trial_id, core_id, tot_cts_count = running.pop(finished_future)
                try:
                    success = finished_future.result()
                    if success:
                        logging.info(f"[SUCCESS] SuperC analysis: {fuzzer} on {benchmark}, trial {trial_id}, core {core_id}")
                    else:
                        logging.error(f"[FAILURE] SuperC analysis: {fuzzer} on {benchmark}, trial {trial_id}, core {core_id}")
                except Exception as e:
                    logging.error(f"[EXCEPTION] SuperC analysis: {fuzzer} on {benchmark}, trial {trial_id}, core {core_id} -> {e}")

                # Launch next task (reuse freed core)
                if tasks:
                    next_fuzzer, next_bench, next_trial, next_tot_cts = tasks.pop(0)
                    new_future = executor.submit(
                        run_superc,
                        next_fuzzer,
                        next_bench,
                        next_trial,
                        experiment_state["experiment_path"],
                        core_id,  # reuse same core
                        data_storage,
                        experiment_state["total_memory_needed_gb"]
                    )
                    running[new_future] = (next_fuzzer, next_bench, next_trial, core_id, next_tot_cts)
                    logging.info(f"[START] SuperC analysis: {next_fuzzer} on {next_bench}, trial {next_trial}, core {core_id}")

                # Break after processing one finished future
                break


def triage_on_experiments(experiment_state):
    built_benchmarks = experiment_state["built_benchmarks"]
    coverage_binaries = experiment_state["coverage_binaries"]
    experiment_path = experiment_state["experiment_path"]
    data_storage = os.path.join(experiment_path, "data")
    os.makedirs(data_storage, exist_ok=True)

    # cores = experiment_state["cores_range"]
    # max_workers = len(cores)
    # logging.info(f"Detected cores: {cores}, using up to {max_workers} workers")

    core_range = experiment_state["cores_range"]
    core_start = core_range[0]
    core_end = core_range[1]
    max_workers = core_end - core_start + 1
    cores = [core for core in range(core_start, core_end + 1)]
    logging.info(f"Core range: {core_range}, using up to {max_workers} workers")

    # --- Collect all triage tasks ---
    tasks = []
    for benchmark in built_benchmarks:
        tot_cts_count = experiment_state["tot_cts"].get(benchmark, 1)
        for fuzzer in built_benchmarks[benchmark]:
            for triager in experiment_state["built_triagers"]:
                tasks.append((triager, fuzzer, benchmark, tot_cts_count))

    # --- Initialize executor ---
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        core_cycle = itertools.cycle(cores)  # Round-robin core assignment
        running = {}  # Map futures → (task, core_id)

        # Start initial batch
        for _ in range(min(max_workers, len(tasks))):
            triager, fuzzer, benchmark, tot_cts_count = tasks.pop(0)
            core_id = next(core_cycle)
            future = executor.submit(
                run_triaging,
                triager,
                fuzzer,
                benchmark,
                experiment_state["trials"],
                experiment_state["experiment_path"],
                core_id,
                data_storage,
                experiment_state["total_memory_needed_gb"]
            )
            running[future] = (triager, fuzzer, benchmark, core_id, tot_cts_count)
            logging.info(f"[START] Triaging {fuzzer} on {benchmark}, core {core_id} using {triager}")

        # As tasks finish, schedule new ones on the freed core
        while running:
            for finished_future in as_completed(list(running.keys()), timeout=None):
                triager, fuzzer, benchmark, core_id, tot_cts_count = running.pop(finished_future)
                try:
                    success = finished_future.result()
                    if success:
                        logging.info(f"[SUCCESS] Completed Triaging {fuzzer} on {benchmark}, core {core_id} using {triager}, total cts {tot_cts_count}")
                    else:
                        logging.error(f"[FAILURE] Failed Triaging {fuzzer} on {benchmark}, core {core_id} using {triager}, total cts {tot_cts_count}")
                except Exception as e:
                    logging.error(f"[EXCEPTION] Triaging {triager} with {fuzzer} on {benchmark}, core {core_id} -> {e}")

                # Launch next task on freed core
                if tasks:
                    next_triager, next_fuzzer, next_bench, next_tot_cts = tasks.pop(0)
                    new_future = executor.submit(
                        run_triaging,
                        next_triager,
                        next_fuzzer,
                        next_bench,
                        experiment_state["trials"],
                        experiment_state["experiment_path"],
                        core_id,  # reuse same core
                        data_storage,
                        experiment_state["total_memory_needed_gb"]
                    )
                    running[new_future] = (next_triager, next_fuzzer, next_bench, core_id, next_tot_cts)
                    logging.info(f"[START] Triaging {next_fuzzer} on {next_bench}, core {core_id} using {next_triager}")

                # Break after processing one finished future
                break



if __name__ == "__main__":
    # Set up logging
    logging = get_logger(__name__)
    
    logging.info("Starting experiment setup...")

    # Process arguments
    parser = argparse.ArgumentParser(description="Run experiments.")
    parser.add_argument("--config", type=str, required=True, help="Path to the configuration file.")
    parser.add_argument("--fuzzers", type=str, nargs='+', required=True, help="List of fuzzers to run.")
    parser.add_argument("--bug-triaging", type=str, nargs='+', required=False, default=[], help="List of Triaging Tools to run.")
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
        "bug_triaging": args.bug_triaging,
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
        "experiment_memory": config["experiment_memory"],
        "random_seed": config["random_seed"] 
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
        logging.warning(f"One or multiple filestores does not exist.")
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
    if build_runner_image(runner_image, project_root):
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

    # Validate and build selected triaging tools
    if experiment_state["bug_triaging"]:
        logging.info("Validating Triaging tools...")
        validate_triagers(experiment_state["bug_triaging"], project_root)
        logging.info("Triagers validated successfully.")
        logging.info("Building selected Triagers...")
        built_triagers = []
        triager_failures = []
        with ThreadPoolExecutor(max_workers=experiment_state["cores_to_use"]) as executor:  # adjust max_workers as needed
            future_to_triagers = {
                executor.submit(build_bug_triager, bug_triager, experiment_path, project_root): bug_triager
                for bug_triager in experiment_state['bug_triaging']
            }

            for future in as_completed(future_to_triagers):
                triager = future_to_triagers[future]
                try:
                    success = future.result()
                    if success:
                        built_triagers.append(triager)
                    else:
                        triager_failures.append(triager)
                except Exception as e:
                    # if build_fuzzer itself raises
                    triager_failures.append(triager)
                    logging.error(f"Error building {triager}: {e}")

        if triager_failures:
            logging.warning(f"Triager build failures: {triager_failures}")    
        logging.success(f"Triagers built successfully: {built_triagers}")

        experiment_state["built_triagers"] = built_triagers
        experiment_state["triager_failures"] = triager_failures

    # Build SuperC CFG analysis container
    logging.info("Building SuperC CFG analysis container...")
    superc_path = "cfg-analysis"
    if build_superc(superc_path, experiment_path, project_root):
        logging.success("SuperC container built successfully.")
    else:
        logging.error("Failed to build SuperC container.")
        sys.exit(1)

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
    failed_strategies = []
    tot_cts = {}

    for strategy in experiment_state["compiletime"]:
        try:
            new_benchmark_mapping, new_tot_cts = apply_ct_strategy(strategy,
                                    project_root,
                                    experiment_state["benchmarks"],
                                    experiment_state["random_seed"]         
                                )
            if new_benchmark_mapping:
                benchmark_mappings.update(new_benchmark_mapping)
                tot_cts.update(new_tot_cts)
            else:
                failed_strategies.append(strategy)
        except Exception as e:
            logging.error(f"Error applying compile-time strategy {strategy}: {e}")
            failed_strategies.append(strategy)
    
    experiment_state["benchmark_mappings"] = benchmark_mappings
    experiment_state["failed_strategies"] = failed_strategies
    experiment_state["tot_cts"] = tot_cts
    
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
                    logging.info(f"Successfully built benchmark: {fuzzer}_{benchmark}")
                    fuzzer_benchmark_pairs.append(f"{fuzzer}_{benchmark}")

                    if benchmark not in built_benchmarks:
                        built_benchmarks[benchmark] = [fuzzer]
                    else:
                        built_benchmarks[benchmark].append(fuzzer)

                else:
                    logging.error(f"Failed to build benchmark: {fuzzer}_{benchmark}")
                    if benchmark not in benchmark_failures:
                        benchmark_failures[benchmark] = [fuzzer]
                    else:
                        benchmark_failures[benchmark].append(fuzzer)

            except Exception as e:
                logging.error(f"Exception while building {fuzzer}_{benchmark}: {e}")
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
    logging.debug(f"Experiment state after resource allocation: {pprint.pformat(experiment_state)}")
    # Save the state
    with open(f"{experiment_state['experiment_path']}/experiment_state.pkl", "wb") as f:
        pickle.dump(experiment_state, f)

    # Run experiments
    logging.info("Ready to begin experiments!")
    run_experiments(experiment_state)

    # Run SuperC CFG analysis on experiments
    logging.info("Experiments completed. Starting SuperC CFG analysis...")
    run_superc_on_experiments(experiment_state, logging)
    logging.info("SuperC CFG analysis completed.")

    if experiment_state.get("built_triagers"):
        logging.info("Starting triaging...")
        triage_on_experiments(experiment_state)
        logging.info("Triaging completed.")
    
    

    
    # Collect results
    # Print summary
    
    # Cleanup
    delete_cts_benchmarks(experiment_state, project_root)
