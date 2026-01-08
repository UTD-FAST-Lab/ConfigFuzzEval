from os.path import isdir
from color_logger import get_logger
import pickle
import argparse
import os, subprocess
from run_experiment import delete_cts_benchmarks, run_superc_on_experiments, triage_on_experiments

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
            coverage_binary_location = f"{experiment_state['experiment_path']}/benchmarks/coverage_cts_{strategy}_{library}_{program}_{trial_num}"
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



if __name__ == "__main__":
    # Set up logging
    logging = get_logger(__name__)
    

    # Process arguments
    parser = argparse.ArgumentParser(description="Reload the benchmark state and run post-analysis.")
    parser.add_argument("--state", type=str, required=True, help="Path to the experiment state")
    parser.add_argument("--cov", action="store_true", help="Calculate Coverage")
    parser.add_argument("--superc", action="store_true", help="Run SuperC on results (assumes pre-processing complete)")
    parser.add_argument("--triage", action="store_true", help="Run selected bug triaging")
    parser.add_argument("--clean", action="store_true", help="Clean any artifacts")
    
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

    if args.superc:
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
    
    # Cleanup
    if args.clean:
        project_root = experiment_state['project_root']
        delete_cts_benchmarks(experiment_state, project_root)
