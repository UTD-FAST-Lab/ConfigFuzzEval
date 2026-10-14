import os
import sys
import yaml
import argparse
from docker_image_builder import build_base_image, build_fuzzer,build_bug_triager, build_benchmark, run_benchmark,run_triaging, build_runner_image, build_superc, run_superc, run_label
from color_logger import get_logger
from resource_allocation import allocate_resources
from validation import validate_configuration, validate_fuzzers, validate_benchmarks, validate_ct_strategies, validate_triagers, validate_rt_strategies, validate_runs
from rt_config_generator import generate_rt_configs, load_supported_fuzzers
from ct_strategy_applicator import apply_ct_strategy, count_ct_configurations
from experiment_plan import load_experiment_file, expand_groups, unique
from concurrent.futures import ThreadPoolExecutor, as_completed
import pprint
import itertools
import pickle, shutil

def plan_trial_tasks(experiment_state):
    """Every trial of the experiment's runs whose fuzzer and benchmark copy built, as
    (fuzzer, runtime strategy, benchmark copy, trial, #compile-time configs, rt config file, max_total_time)."""
    tasks = []
    for run in experiment_state["runs"]:
        copies = experiment_state["benchmark_mappings"].get((run["compiletime"], run["benchmark"]), [])
        for benchmark in copies:
            if run["fuzzer"] not in experiment_state["built_benchmarks"].get(benchmark, []):
                continue
            tot_cts_count = experiment_state["tot_cts"].get(benchmark, 1)
            for trial_id in range(run["trials"]):
                rt_config_file = experiment_state["rt_configs"].get((run["runtime_strategy"], run["benchmark"], trial_id))
                tasks.append((run["fuzzer"], run["runtime_strategy"], benchmark, trial_id, tot_cts_count,
                              rt_config_file, run["max_total_time"]))
    return tasks


def trial_tasks(experiment_state):
    """The experiment's trials (see plan_trial_tasks). Experiments saved before
    experiment files existed have none stored: every built fuzzer x benchmark x
    runtime strategy ran trials x max_total_time, so rebuild that."""
    if "trial_tasks" in experiment_state:
        return experiment_state["trial_tasks"]
    tasks = []
    supported = experiment_state.get("rt_supported_fuzzers", {})
    for benchmark, fuzzers in experiment_state["built_benchmarks"].items():
        tot_cts_count = experiment_state["tot_cts"].get(benchmark, 1)
        base_benchmark = experiment_state.get("base_benchmarks", {}).get(benchmark, benchmark)
        for fuzzer in fuzzers:
            strategies = experiment_state.get("runtime_strategies", ["default"]) if fuzzer in supported else ["default"]
            for rts in strategies:
                for trial_id in range(experiment_state["trials"]):
                    rt_config_file = experiment_state.get("rt_configs", {}).get((rts, base_benchmark, trial_id))
                    tasks.append((fuzzer, rts, benchmark, trial_id, tot_cts_count, rt_config_file,
                                  experiment_state["max_total_time"]))
    return tasks


def run_trials(experiment_state):
    """{"<run label>_<benchmark copy>": number of trials}, the names of the result folders."""
    counts = {}
    for fuzzer, rts, benchmark, *_ in trial_tasks(experiment_state):
        name = f"{run_label(fuzzer, rts)}_{benchmark}"
        counts[name] = counts.get(name, 0) + 1
    return counts


def aggregate_results(experiment_state):
    logging = get_logger(__name__)
    experiment_path = experiment_state["experiment_path"]
    data_storage = os.path.join(experiment_path, "data")

    for pair, trials in run_trials(experiment_state).items():
        # Get the result, put it in config id 0
        for trail_num in range(trials):
            result_file = os.path.join(data_storage, f"{pair}_trial_{trail_num}/coverage/report.json")
            if not os.path.exists(result_file):
                logging.error(f"Result file does not exist for {pair} trial {trail_num}: {result_file}")
                continue
            
            # slice the pair to get config id 0, the id is at the end
            dest_dir_name = "_".join(pair.split("_")[:-1]) + "_0" + "_trial" + "_" + str(trail_num)
            dest_data_loc = os.path.join(data_storage, dest_dir_name, "lcov_results")
            os.makedirs(dest_data_loc, exist_ok=True)
            
            # copy the report json to the new location and rename it to according to the config id
            shutil.copy(result_file, os.path.join(dest_data_loc, f"{pair}_report.json"))


def delete_cts_benchmarks(experiment_state, project_root):
    benchmark_dir = os.path.join(project_root, "benchmarks")
    
    all_cts_benchmarks = set(experiment_state["built_benchmarks"]) | set(experiment_state["benchmark_failures"])
    
    for benchmark in all_cts_benchmarks:
        benchmark_path = os.path.join(benchmark_dir, benchmark)
        if os.path.exists(benchmark_path):
            try:
                # Remove the benchmark directory
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
    # One per trial of every run (fuzzer, benchmark copy, runtime strategy); a
    # runtime strategy reuses the fuzzer's normal benchmark build.
    tasks = []
    for task in trial_tasks(experiment_state):
        if task[2] not in coverage_binaries:
            logging.error(f"[SKIPPED] {run_label(task[0], task[1])} on {task[2]}, trial {task[3]}: "
                          f"its coverage binary failed to build")
            continue
        tasks.append(task)

    def submit(executor, task, core_id):
        fuzzer, rts, benchmark, trial_id, tot_cts_count, rt_config_file, max_total_time = task
        logging.info(f"[START] {run_label(fuzzer, rts)} on {benchmark}, trial {trial_id}, core {core_id}")
        return executor.submit(
            run_benchmark,
            fuzzer,
            benchmark,
            coverage_binaries[benchmark],
            experiment_state["report_path"],
            max_total_time,
            experiment_state["trials"],
            trial_id,
            experiment_state["experiment_path"],
            core_id,
            data_storage,
            experiment_state["total_memory_needed_gb"],
            tot_cts_count,
            rts,
            rt_config_file,
            experiment_state["min_config_time"],
        )

    # --- Initialize executor ---
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        core_cycle = itertools.cycle(cores)  # Round-robin assignment of cores
        running = {}  # Map of futures → (task, core_id)

        # Start initial batch
        for _ in range(min(max_workers, len(tasks))):
            task = tasks.pop(0)
            core_id = next(core_cycle)
            running[submit(executor, task, core_id)] = (task, core_id)

        # As tasks finish, schedule new ones on the freed core
        while running:
            for finished_future in as_completed(list(running.keys()), timeout=None):
                task, core_id = running.pop(finished_future)
                fuzzer, rts, benchmark, trial_id = task[:4]
                label = run_label(fuzzer, rts)
                try:
                    success = finished_future.result()
                    if success:
                        logging.info(f"[SUCCESS] {label} on {benchmark}, trial {trial_id}, core {core_id}")
                    else:
                        logging.error(f"[FAILURE] {label} on {benchmark}, trial {trial_id}, core {core_id}")
                except Exception as e:
                    logging.error(f"[EXCEPTION] {label} on {benchmark}, trial {trial_id}, core {core_id} -> {e}")

                # Launch next task (reuse freed core)
                if tasks:
                    task = tasks.pop(0)
                    running[submit(executor, task, core_id)] = (task, core_id)

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
    # Every (fuzzer, benchmark copy, trial) that ran; runtime strategies share them.
    tasks = []
    for benchmark in built_benchmarks:
        if benchmark.split("_")[-1] != "0":
            logging.warning(f"Skipping SuperC analysis for {benchmark} as it does not correspond to config id 0")
    for fuzzer, _, benchmark, trial_id, tot_cts_count, *_ in trial_tasks(experiment_state):
        if benchmark.split("_")[-1] == "0":
            tasks.append((fuzzer, benchmark, trial_id, tot_cts_count))
    tasks = unique(tasks)

    logging.debug(f"Collected SuperC analysis tasks: {pprint.pformat(tasks)}")
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
    # One per triager and (fuzzer, benchmark copy) that ran, over its trials.
    trials_of = {}
    for fuzzer, _, benchmark, trial_id, *_ in trial_tasks(experiment_state):
        trials_of[(fuzzer, benchmark)] = max(trials_of.get((fuzzer, benchmark), 0), trial_id + 1)
    tasks = []
    for (fuzzer, benchmark), trials in trials_of.items():
        tot_cts_count = experiment_state["tot_cts"].get(benchmark, 1)
        for triager in experiment_state["built_triagers"]:
            tasks.append((triager, fuzzer, benchmark, tot_cts_count, trials))

    # --- Initialize executor ---
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        core_cycle = itertools.cycle(cores)  # Round-robin core assignment
        running = {}  # Map futures → (task, core_id)

        # Start initial batch
        for _ in range(min(max_workers, len(tasks))):
            triager, fuzzer, benchmark, tot_cts_count, trials = tasks.pop(0)
            core_id = next(core_cycle)
            future = executor.submit(
                run_triaging,
                triager,
                fuzzer,
                benchmark,
                trials,
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
                    next_triager, next_fuzzer, next_bench, next_tot_cts, next_trials = tasks.pop(0)
                    new_future = executor.submit(
                        run_triaging,
                        next_triager,
                        next_fuzzer,
                        next_bench,
                        next_trials,
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
    parser = argparse.ArgumentParser(
        description="Run experiments. What to run comes either from an experiment file (--experiment) "
                    "or from --fuzzers/--benchmarks/--compiletime/--runtime-strategy; see README.md.")
    parser.add_argument("--config", type=str, required=True, help="Path to the configuration file (machine settings, default trials and max_total_time).")
    parser.add_argument("--experiment", "--groups", type=str, help="Experiment file (YAML, or JSON if it ends in .json) with groups of fuzzers, benchmarks and strategies. Replaces --fuzzers/--benchmarks/--compiletime/--runtime-strategy.")
    parser.add_argument("--fuzzers", type=str, nargs='+', help="List of fuzzers to run (without --experiment).")
    parser.add_argument("--bug-triaging", type=str, nargs='+', help="List of Triaging Tools to run (overrides the experiment file's bug_triaging).")
    parser.add_argument("--benchmarks", type=str, nargs='+', help="List of benchmarks to run (without --experiment).")
    parser.add_argument("--compiletime", type=str, nargs='+', help="Compile time strategies to use (without --experiment; default: default).")
    parser.add_argument("--runtime-strategy", type=str, nargs='+',
                        help="Run-time configuration strategies (runtime/<strategy>; without --experiment; default: default). "
                             "Non-default strategies need every fuzzer to be in runtime/supported_fuzzers.json; otherwise the experiment stops with an error.")
    parser.add_argument("--experiment-name", type=str, help="Name of the experiment (overrides the experiment file's experiment_name).")
    parser.add_argument("--no-superc", action="store_true", help="Disable SuperC CFG analysis (skips building and running the SuperC container).")
    parser.add_argument("--dry-run", action="store_true", help="Validate everything and print the planned runs and trials, then exit without building or running anything.")

    args = parser.parse_args()

    # Read configuration
    with open(args.config, "r") as f:
        config = yaml.safe_load(f)

    # Validate configuration
    validate_configuration(config)
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    rt_supported_fuzzers = load_supported_fuzzers(project_root)
    defaults = {"trials": config["trials"], "max_total_time": config["max_total_time"]}

    # What to run: groups from the experiment file, or one group from the flags.
    if args.experiment:
        given = [flag for flag, value in [("--fuzzers", args.fuzzers), ("--benchmarks", args.benchmarks),
                                          ("--compiletime", args.compiletime),
                                          ("--runtime-strategy", args.runtime_strategy)] if value]
        if given:
            logging.error(f"--experiment (--groups) replaces {', '.join(given)}; put them in the experiment file's groups.")
            sys.exit(1)
        experiment_file = load_experiment_file(args.experiment)
        groups = experiment_file["groups"]
        experiment_name = args.experiment_name or experiment_file.get("experiment_name")
        no_superc = args.no_superc or experiment_file.get("no_superc", False)
        bug_triaging = args.bug_triaging if args.bug_triaging is not None else experiment_file["bug_triaging"]
        runs = expand_groups(groups, defaults, overrides=experiment_file["benchmarks"])
    else:
        if not args.fuzzers or not args.benchmarks:
            logging.error("Give --experiment FILE, or --fuzzers and --benchmarks.")
            sys.exit(1)
        groups = [{"fuzzers": args.fuzzers, "benchmarks": args.benchmarks,
                   "compiletime": args.compiletime or ["default"],
                   "runtime_strategy": args.runtime_strategy or ["default"]}]
        experiment_name = args.experiment_name
        no_superc = args.no_superc
        bug_triaging = args.bug_triaging or []
        runs = expand_groups(groups, defaults)
    if not experiment_name:
        logging.error("No experiment name: give --experiment-name, or experiment_name in the experiment file.")
        sys.exit(1)

    # Check every name before building anything.
    fuzzers = unique(r["fuzzer"] for r in runs)
    benchmarks = unique(r["benchmark"] for r in runs)
    compiletime = unique(r["compiletime"] for r in runs)
    runtime_strategies = unique(r["runtime_strategy"] for r in runs)
    validate_fuzzers(fuzzers, project_root)
    validate_benchmarks(benchmarks, project_root)
    validate_ct_strategies(compiletime, project_root)
    validate_rt_strategies(runtime_strategies, project_root)
    if bug_triaging:
        validate_triagers(bug_triaging, project_root)
    # Then every fuzzer x benchmark x strategy combination: one that cannot run is an
    # error, listed with all the others, before anything is built.
    validate_runs(runs, project_root)

    if args.dry_run:
        logging.info(f"Dry run of experiment {experiment_name} (nothing is built, copied or run).")
        # Benchmark copies per (compile-time strategy, benchmark); each copy is built
        # once per fuzzer that runs on it and gets max_total_time / copies per trial.
        copies = {}
        for key in unique((r["compiletime"], r["benchmark"]) for r in runs):
            copies[key] = count_ct_configurations(key[0], project_root, key[1], config["random_seed"])
        total_trials = total_seconds = 0
        for run in runs:
            n = copies[(run["compiletime"], run["benchmark"])]
            total_trials += n * run["trials"]
            total_seconds += run["trials"] * run["max_total_time"]
            logging.info(f"  group {run['group']}: {run_label(run['fuzzer'], run['runtime_strategy'])} on "
                         f"{run['benchmark']}, compiletime {run['compiletime']} ({n} benchmark cop{'y' if n == 1 else 'ies'}), "
                         f"{run['trials']} trial(s) x {run['max_total_time']} s")
        builds = sum(copies[(ct, b)] for _, ct, b in unique((r["fuzzer"], r["compiletime"], r["benchmark"]) for r in runs))
        logging.info(f"Fuzzers to build: {fuzzers}")
        logging.info(f"Benchmark builds: {builds}, plus {sum(copies.values())} coverage build(s)")
        logging.info(f"Trials: {total_trials}, {total_seconds / 3600:.1f} fuzzing hours in total; "
                     f"with {config['cores_to_use']} cores at least {total_seconds / 3600 / config['cores_to_use']:.1f} hours.")
        logging.info(f"SuperC: {'disabled' if no_superc else 'enabled'}; bug triaging: {bug_triaging or 'none'}")
        sys.exit(0)

    # Save all to a state
    experiment_state = {
        "fuzzers": fuzzers,
        "benchmarks": benchmarks,
        "bug_triaging": bug_triaging,
        "compiletime": compiletime,
        "runtime_strategies": runtime_strategies,
        # One entry per fuzzer x benchmark x compile-time x runtime strategy, with its trials and max_total_time.
        "runs": runs,
        "groups": groups,
        # Minimum fuzzing time per configuration under a runtime strategy, in seconds.
        "min_config_time": config.get("min_config_time", 60),
        # Docker images built at the same time. Many parallel builds on a slow disk make
        # Docker time out (DeadlineExceeded), so this is capped separately from cores_to_use.
        "build_parallelism": min(config.get("build_parallelism", 16), config["cores_to_use"]),
        "trials": config["trials"],
        "max_total_time": config["max_total_time"],
        "base_image_path": config["base_image_path"],
        "runner_image_path": config["runner_image_path"],
        "experiment_filestore": config["experiment_filestore"],
        "report_filestore": config["report_filestore"],
        "project_root": project_root,
        "cores_to_use": config["cores_to_use"],
        "first_core": config.get("first_core"),
        "allow_serial_execution": config["allow_serial_execution"],
        "experiment_memory": config["experiment_memory"],
        "random_seed": config["random_seed"] ,
        "serialize_multi_conf": config["serialize_multi_conf"],
        "no_superc": no_superc,
        "rt_supported_fuzzers": rt_supported_fuzzers,
    }
    
    logging.info("Running experiments with the following parameters:")
    logging.info(f"Configuration file: {args.config}")
    logging.info(f"Experiment file: {args.experiment or 'none (command-line flags)'}")
    logging.info(f"Fuzzers: {fuzzers}")
    logging.info(f"Benchmarks: {benchmarks}")
    logging.info(f"Compile time strategies: {compiletime}")
    logging.info(f"Runtime strategies: {runtime_strategies}")
    logging.info(f"Experiment name: {experiment_name}")
    logging.info(f"SuperC analysis: {'disabled' if no_superc else 'enabled'}")
    logging.info(f"Default trials / runtime per trial (seconds), from {args.config}: "
                 f"{experiment_state['trials']} / {experiment_state['max_total_time']}")
    logging.info(f"Parallel image builds: {experiment_state['build_parallelism']}")
    for run in runs:
        logging.info(f"Run (group {run['group']}): {run_label(run['fuzzer'], run['runtime_strategy'])} on "
                     f"{run['benchmark']}, compiletime {run['compiletime']}, "
                     f"{run['trials']} trial(s) x {run['max_total_time']} s")

    # build experiment in filestore
    experiment_filestore = experiment_state["experiment_filestore"]
    report_filestore = experiment_state["report_filestore"]
    
    if not (os.path.exists(experiment_filestore) and os.path.exists(report_filestore)):
        logging.warning(f"One or multiple filestores does not exist.")
        os.makedirs(experiment_filestore, exist_ok=True)
        os.makedirs(report_filestore, exist_ok=True)
    
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

    # Keep what this experiment ran with it: the experiment file as given, or the
    # flags' single group written out in the same format.
    if args.experiment:
        shutil.copy(args.experiment, os.path.join(experiment_path, "experiment" + os.path.splitext(args.experiment)[1]))
    else:
        with open(os.path.join(experiment_path, "experiment.yaml"), "w") as f:
            yaml.safe_dump({"experiment_name": experiment_name, "no_superc": no_superc,
                            "bug_triaging": bug_triaging, "groups": groups}, f, sort_keys=False)
    
    # Build base image
    logging.info("Building base image...")
    base_image = experiment_state["base_image_path"]
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
        

    # Build selected fuzzers (validated above, before anything was built)
    logging.info("Building selected fuzzers...")
    built_fuzzers = []
    fuzzer_failures = []
    with ThreadPoolExecutor(max_workers=experiment_state["build_parallelism"]) as executor:
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

    # Build selected triaging tools (validated above)
    if experiment_state["bug_triaging"]:
        logging.info("Building selected Triagers...")
        built_triagers = []
        triager_failures = []
        with ThreadPoolExecutor(max_workers=experiment_state["build_parallelism"]) as executor:
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
    if experiment_state["no_superc"]:
        logging.info("SuperC disabled (--no-superc). Skipping SuperC container build.")
    else:
        logging.info("Building SuperC CFG analysis container...")
        superc_path = "cfg-analysis"
        if build_superc(superc_path, experiment_path, project_root):
            logging.success("SuperC container built successfully.")
        else:
            logging.error("Failed to build SuperC container.")
            sys.exit(1)

    # Apply compile-time strategies (validated above), each only to the benchmarks
    # that some run uses it with.
    logging.info("Applying selected compile-time strategies...")

    benchmark_mappings = {}
    failed_strategies = []
    tot_cts = {}

    for strategy in experiment_state["compiletime"]:
        try:
            new_benchmark_mapping, new_tot_cts = apply_ct_strategy(strategy,
                                    project_root,
                                    unique(r["benchmark"] for r in runs if r["compiletime"] == strategy),
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

    # Each fuzzer is built only against the benchmark copies its runs use.
    builds_to_run = unique(
        (run["fuzzer"], benchmark)
        for run in runs if run["fuzzer"] in built_fuzzers
        for benchmark in benchmark_mappings.get((run["compiletime"], run["benchmark"]), []))

    # Run benchmark builds in parallel
    with ThreadPoolExecutor(max_workers=experiment_state["build_parallelism"]) as executor:
        future_to_pair = {
            executor.submit(build_benchmark, fuzzer, benchmark, experiment_path, project_root): (fuzzer, benchmark)
            for fuzzer, benchmark in builds_to_run
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

    with ThreadPoolExecutor(max_workers=experiment_state["build_parallelism"]) as executor:
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

    # Runtime strategies: copy the sampling code into the experiment (so editing
    # runtime/ cannot change a running experiment) and generate the configurations.
    base_benchmarks = {}
    for (_, benchmark), cts_benchmarks in benchmark_mappings.items():
        for cts_benchmark in cts_benchmarks:
            base_benchmarks[cts_benchmark] = benchmark
    experiment_state["base_benchmarks"] = base_benchmarks
    experiment_state["rt_configs"] = {}
    # (runtime strategy, benchmark) -> most trials any run needs configurations for
    rt_trials = {}
    for run in runs:
        if run["runtime_strategy"] != "default" and run["fuzzer"] in built_fuzzers:
            key = (run["runtime_strategy"], run["benchmark"])
            rt_trials[key] = max(rt_trials.get(key, 0), run["trials"])
    if rt_trials:
        logging.info("Generating runtime strategy configurations...")
        shutil.copytree(os.path.join(project_root, "runtime"), os.path.join(experiment_path, "runtime"),
                        ignore=shutil.ignore_patterns("__pycache__"), dirs_exist_ok=True)
        for (strategy, benchmark), trials in rt_trials.items():
            experiment_state["rt_configs"].update(generate_rt_configs(
                [strategy], [benchmark], trials, experiment_path, project_root, experiment_state["random_seed"]))

    # Every trial to run, and the result folder names with their trial counts.
    experiment_state["trial_tasks"] = plan_trial_tasks(experiment_state)
    experiment_state["run_pairs"] = list(run_trials(experiment_state))

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

    logging.info("Experiments completed. Starting result aggregation...")
    aggregate_results(experiment_state)

    # Run SuperC CFG analysis on experiments
    if experiment_state["no_superc"]:
        logging.info("Aggregation completed. SuperC disabled (--no-superc), skipping SuperC CFG analysis.")
    else:
        logging.info("Aggregation completed. Starting SuperC CFG analysis...")
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
