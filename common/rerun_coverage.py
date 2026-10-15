"""Redoes the coverage of a finished experiment's trials on their existing fuzzer
output, with the current fuzzers/<fuzzer>/coverage.py of this repository (the
experiment's own copy is not changed).

Each trial's coverage/ is first renamed to coverage_previous/ (kept if it already
exists, so the first results stay), then the coverage runner image runs as in the
experiment, trials in parallel on the given cores. Afterwards the lcov_results copies
are refreshed, as at the end of an experiment.

    python3 common/rerun_coverage.py --experiment-path /path/to/experiment-data/NAME \\
        --fuzzer vafuzz --cores 54 > logs-reports/NAME_coverage_rerun.log 2>&1
"""

import argparse
import json
import os
import pickle
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

from color_logger import get_logger
from docker_image_builder import run_coverage

logging = get_logger(__name__)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def keep_previous_coverage(trial_dir):
    """Rename coverage/ to coverage_previous/ (both are written by root in the container)."""
    if os.path.isdir(os.path.join(trial_dir, "coverage_previous")):
        return
    if os.path.isdir(os.path.join(trial_dir, "coverage")):
        subprocess.run(["docker", "run", "--rm", "-v", f"{trial_dir}:/trial", "fbpp/runner-coverage",
                        "mv", "/trial/coverage", "/trial/coverage_previous"], check=True)


def main():
    parser = argparse.ArgumentParser(description="Redo the coverage of a finished experiment.")
    parser.add_argument("--experiment-path", required=True, help="<experiment_filestore>/<experiment name>")
    parser.add_argument("--fuzzer", nargs="+", help="Only trials of these fuzzers (default: all).")
    parser.add_argument("--match", help="Only trial folders whose name matches this regular expression.")
    parser.add_argument("--cores", type=int, required=True, help="Number of cores to use (trials run in parallel).")
    parser.add_argument("--first-core", type=int, help="First core to use (default: the last --cores cores). "
                        "A trial on core c runs on CPUs c-1 and c, so it must be at least 1.")
    args = parser.parse_args()

    experiment_path = os.path.abspath(args.experiment_path)
    with open(os.path.join(experiment_path, "experiment_state.pkl"), "rb") as f:
        state = pickle.load(f)
    # The saved paths are those of the run; the folder may have been renamed since.
    state["experiment_path"] = experiment_path
    data = os.path.join(experiment_path, "data")

    trials = []
    for name in sorted(os.listdir(data)):
        info_file = os.path.join(data, name, "trial_info.json")
        if not os.path.isfile(info_file) or (args.match and not re.search(args.match, name)):
            continue
        with open(info_file) as f:
            info = json.load(f)
        if args.fuzzer and info["fuzzer"] not in args.fuzzer:
            continue
        trials.append((name, info))
    if not trials:
        logging.error("No trials selected.")
        sys.exit(1)

    first = args.first_core if args.first_core is not None else os.cpu_count() - args.cores
    if first < 1 or first + args.cores > os.cpu_count():
        logging.error(f"Cores {first} to {first + args.cores - 1} do not fit cores 1 to {os.cpu_count() - 1}.")
        sys.exit(1)
    free_cores = list(range(first, first + args.cores))
    scripts = {fuzzer: os.path.join(PROJECT_ROOT, "fuzzers", fuzzer, "coverage.py")
               for fuzzer in {info["fuzzer"] for _, info in trials}}
    logging.info(f"Redoing coverage of {len(trials)} trials on cores {first} to {first + args.cores - 1} "
                 f"with {', '.join(scripts.values())}")

    def redo(name, info, core):
        trial_dir = os.path.join(data, name)
        multi_config_args = []
        if info["runtime_strategy"] != "default":
            rts, base = info["runtime_strategy"], state["base_benchmarks"].get(info["benchmark"], info["benchmark"])
            rt_config_file = os.path.join(experiment_path, "rt_configs", rts, base, f"trial_{info['trial']}.json")
            multi_config_args = [
                "-e", "MULTI_CONFIG=1", "-e", f"FUZZER_NAME={info['fuzzer']}",
                "-v", f"{os.path.join(experiment_path, 'runtime')}:/runtime:ro",
                "-v", f"{rt_config_file}:/rt_configs.json:ro",
            ]
        keep_previous_coverage(trial_dir)
        with open(os.path.join(trial_dir, "coverage_rerun.log"), "w") as lf:
            run_coverage(info["fuzzer"], info["benchmark"], experiment_path, core, trial_dir, lf,
                         multi_config_args, coverage_script=scripts[info["fuzzer"]])
        return os.path.isfile(os.path.join(trial_dir, "coverage", "report.txt"))

    failed = []
    with ThreadPoolExecutor(max_workers=args.cores) as executor:
        pending, running = list(trials), {}
        while pending or running:
            while pending and free_cores:
                name, info = pending.pop(0)
                core = free_cores.pop(0)
                running[executor.submit(redo, name, info, core)] = (name, core)
            done = next(as_completed(running))
            name, core = running.pop(done)
            free_cores.append(core)
            try:
                ok = done.result()
            except Exception as e:
                logging.error(f"{name}: {e}")
                ok = False
            if not ok:
                failed.append(name)
            logging.info(f"[{len(trials) - len(pending) - len(running)}/{len(trials)}] "
                         f"{'done' if ok else 'FAILED'}: {name}")

    # Refresh the lcov_results copies, as at the end of an experiment
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from run_experiment import aggregate_results
    aggregate_results(state)
    if failed:
        logging.error(f"No report.txt for {len(failed)} trials (see their coverage_rerun.log): {failed}")
        sys.exit(1)
    logging.success(f"Coverage redone for all {len(trials)} trials.")


if __name__ == "__main__":
    main()
