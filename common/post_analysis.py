from os.path import isdir
from color_logger import get_logger
import pickle
import argparse
import os, subprocess, sys, json
from run_experiment import delete_cts_benchmarks, run_superc_on_experiments, triage_on_experiments, aggregate_results
from docker_image_builder import build_superc, experiment_label
from statistical_analysis import generate_statistics_report, METRICS

def calc_coverage(experiment_state):
    fuzzer_results_dir = f"{experiment_state['experiment_path']}/data"

    for fuzz_result in os.listdir(fuzzer_results_dir):
        full_path = os.path.join(fuzzer_results_dir, fuzz_result)
        if os.path.isdir(full_path):
            fuzz_result_ls = fuzz_result.split('_')
            print(fuzz_result_ls)

            fuzzer, strategy, library, program, cts_num, trial_num = \
                fuzz_result_ls[0],  fuzz_result_ls[2],  fuzz_result_ls[3], \
                 fuzz_result_ls[4],  fuzz_result_ls[5],  fuzz_result_ls[7]
            
            print(fuzzer, strategy, library, program, cts_num, trial_num)
            
            
            # Need coreID, coverage_binary_location, fuzzer_location, individual_data_storage
            core_id = experiment_state['cores_range'][0]
            coverage_binary_location = f"{experiment_state['experiment_path']}/benchmarks/coverage_cts_{strategy}_{library}_{program}_0"
            fuzzer_location = f"{experiment_state['experiment_path']}/fuzzers/{fuzzer}"
            individual_data_storage = full_path
            subprocess.run([
                "docker", "run", "--rm",
                f"--cpuset-cpus={core_id-1}-{core_id}",
                "-v", f"{coverage_binary_location}:/benchmark",
                "-v", f"{fuzzer_location}:/fuzzer",
                "-v", f"{individual_data_storage}:/fuzzer_output",
                "fbpp/runner-coverage"
            ], check=True)


def per_config_coverage(experiment_state):
    """Writes config_<i>/coverage/report.txt and report.json for every configuration of
    the runtime-strategy trials, from the per-configuration profiles that
    runtime/multi_config_coverage.sh keeps, for the configuration-union statistics."""
    data_dir = os.path.join(experiment_state["experiment_path"], "data")
    core_id = experiment_state["cores_range"][0]
    for entry in sorted(os.listdir(data_dir)):
        trial_dir = os.path.join(data_dir, entry)
        info_path = os.path.join(trial_dir, "trial_info.json")
        if not (os.path.isfile(os.path.join(trial_dir, "rt_run.jsonl")) and os.path.isfile(info_path)):
            continue
        with open(info_path) as f:
            cts_benchmark = json.load(f)["benchmark"]
        coverage_benchmark = os.path.join(experiment_state["experiment_path"], "benchmarks", f"coverage_{cts_benchmark}")
        if not os.path.isdir(coverage_benchmark):
            logging.warning(f"No coverage build {coverage_benchmark} for {entry}, skipped")
            continue
        script = (
            "BIN=$(awk '{print $1}' /benchmark/run_target.sh); "
            "for p in /fuzzer_output/config_*/coverage/merged.profdata; do "
            "  [ -f \"$p\" ] || continue; d=$(dirname \"$p\"); "
            "  llvm-cov export $BIN -instr-profile=$p -format=lcov > $d/report.json && "
            "  llvm-cov report $BIN -instr-profile=$p > $d/report.txt; "
            "done")
        logging.info(f"Per-configuration coverage for {entry}")
        subprocess.run([
            "docker", "run", "--rm", *experiment_label(experiment_state["experiment_path"]),
            f"--cpuset-cpus={core_id-1}-{core_id}",
            "-v", f"{coverage_benchmark}:/benchmark:ro",
            "-v", f"{trial_dir}:/fuzzer_output",
            "fbpp/runner-coverage", "bash", "-c", script
        ], check=True)


def statistics_report(experiment_state, metric="branches", baseline=None, compare_to=None, html=True):
    """Statistical analysis of the trials' coverage, written to <report_filestore>/<experiment>/statistics,
    with the combined coverage reports (union and mean) unless html is False."""
    experiment_path = experiment_state["experiment_path"]
    report_path = experiment_state.get("report_path") or os.path.join(
        experiment_state["report_filestore"], os.path.basename(os.path.normpath(experiment_path)))
    return generate_statistics_report(experiment_path, os.path.join(report_path, "statistics"),
                                      metric, baseline, compare_to, html)


if __name__ == "__main__":
    # Set up logging
    logging = get_logger(__name__)
    

    # Process arguments
    parser = argparse.ArgumentParser(description="Reload the benchmark state and run post-analysis.")
    parser.add_argument("--state", type=str, required=True, help="Path to the experiment state")
    parser.add_argument("--cov", action="store_true", help="Calculate Coverage")
    parser.add_argument("--agg", action="store_true", help="Aggregate results")
    parser.add_argument("--superc", action="store_true", help="Run SuperC on results (assumes pre-processing complete)")
    parser.add_argument("--triage", action="store_true", help="Run selected bug triaging")
    parser.add_argument("--clean", action="store_true", help="Clean any artifacts")
    parser.add_argument("--stats", action="store_true",
                        help="Statistical analysis of the trials' coverage, as HTML in the report filestore")
    parser.add_argument("--per-config-coverage", action="store_true",
                        help="Write a coverage report per runtime configuration (needs Docker), for --stats")
    parser.add_argument("--metric", choices=METRICS, default="branches", help="Primary metric for --stats")
    parser.add_argument("--baseline", help="Fuzzer the others are compared against in --stats (default: aflplusplus)")
    parser.add_argument("--compare-to", help="Another experiment folder, for the --stats reproducibility section")
    parser.add_argument("--no-stats-html", action="store_true",
                        help="With --stats, skip the combined coverage reports (union and mean HTML per arm and benchmark)")
    parser.add_argument("--stats-html", action="store_true", help=argparse.SUPPRESS)   # the default now

    args = parser.parse_args()

    logging.info("Recovering experiment state...")

    experiment_state = None
    with open(args.state, "rb") as f:
        experiment_state = pickle.load(f)

    if experiment_state == None:
        logging.error("Experiment state failed to load")
        exit(1)

    if args.cov:
        logging.info("Calculating coverage")
        calc_coverage(experiment_state)

    if args.agg:
        logging.info("Starting result aggregation...")
        aggregate_results(experiment_state)
        logging.info("Result aggregation completed.")

    if args.superc:
        logging.info("Building SuperC container...")
        
        experiment_path = experiment_state["experiment_path"]
        project_root = experiment_state["project_root"]
        if build_superc("cfg-analysis", experiment_path, project_root):
            logging.success("SuperC container built successfully.")
        else:
            logging.error("Failed to build SuperC container.")
            sys.exit(1)

                
        logging.info("Running SuperC CFG analysis")
    
        # Run SuperC CFG analysis on experiments
        run_superc_on_experiments(experiment_state, logging)
        logging.info("SuperC CFG analysis completed.")

    if args.triage:
        if experiment_state.get("built_triagers"):
            logging.info("Starting triaging...")
            triage_on_experiments(experiment_state)
            logging.info("Triaging completed.")
        else:
            logging.error("Triage requested but the state does not have any \"built traigers\"")

    if args.per_config_coverage:
        logging.info("Writing per-configuration coverage reports...")
        per_config_coverage(experiment_state)

    if args.stats:
        logging.info("Running the statistical analysis...")
        path = statistics_report(experiment_state, args.metric, args.baseline, args.compare_to, not args.no_stats_html)
        logging.success(f"Statistics report written to {path}")

    # Cleanup
    if args.clean:
        project_root = experiment_state['project_root']
        delete_cts_benchmarks(experiment_state, project_root)
