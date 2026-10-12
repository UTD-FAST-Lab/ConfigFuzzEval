from color_logger import get_logger
import sys, os
import importlib.util
from shutil import copytree



logging = get_logger(__name__)

def retrieve_configs(benchmark_grammar, strategy_module, random_seed=None):
    try:
        return strategy_module.request_configurations(benchmark_grammar, random_seed=random_seed)
    except Exception as e:
        print(f"[ERROR] Failed retrieving configurations from {strategy_module}: {e}")
        return []



def ct_change_build(benchmark_build, ct_config):
    """
    Replace {{CT_CONFIGURATIONS}} in the build script with the given config.
    """
    try:
        # Read the file
        with open(benchmark_build, "r", encoding="utf-8") as f:
            build_script = f.read()

        # Perform replacement
        new_script = build_script.replace("{{CT_CONFIGURATION}}", str(ct_config))
        logging.debug(new_script)

        # Write back only if changed
        with open(benchmark_build, "w", encoding="utf-8") as f:
            f.write(new_script)

        # Optional: return whether replacement occurred
        return build_script != new_script

    except Exception as e:
        logging.error(f"Error occurred while changing build script: {e}")
        sys.exit(1)   # or: raise


def load_ct_strategy(strategy, project_root):
    strategy_file = os.path.join(f"{project_root}/compiletime/{strategy}", "strategy.py")
    spec = importlib.util.spec_from_file_location(strategy, strategy_file)
    strategy_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(strategy_module)
    return strategy_module


def count_ct_configurations(strategy, project_root, benchmark, random_seed=None):
    """Number of compile-time configurations (benchmark copies) a strategy yields,
    without copying anything (for run_experiment.py --dry-run)."""
    strategy_module = load_ct_strategy(strategy, project_root)
    benchmark_grammar = f"{project_root}/benchmarks/{benchmark}/ct_grammar.json"
    return len(retrieve_configs(benchmark_grammar, strategy_module, random_seed=random_seed))


def apply_ct_strategy(strategy, project_root, benchmarks, random_seed=None):
    mapping = {}

    logging.info(f"Applying compile-time strategy: {strategy}")
    strategy_module = load_ct_strategy(strategy, project_root)

    tot_cts = {}

    for benchmark in benchmarks:
        new_benchmarks = []
        benchmark_path = f"{project_root}/benchmarks/{benchmark}"
        benchmark_grammar = f"{benchmark_path}/ct_grammar.json"

        ct_configurations = retrieve_configs(
            benchmark_grammar, strategy_module,
            random_seed=random_seed
        )
        
        ct_configs_count = len(ct_configurations)
        
        for idx, each_ct_config in enumerate(ct_configurations):
            logging.debug(f"Applying config {each_ct_config} to benchmark {benchmark}")
            
            # copy the benchmark directory into the same directory with a new name:
            new_benchmark_name = f"cts_{strategy}_{benchmark}_{idx}"
            new_benchmark_path = f"{project_root}/benchmarks/{new_benchmark_name}"
            copytree(benchmark_path, new_benchmark_path)
            new_benchmarks.append(new_benchmark_name)

            new_benchmark_build = f"{new_benchmark_path}/build.sh"
            
            tot_cts[new_benchmark_name] = ct_configs_count
            
            if not os.path.exists(new_benchmark_build):
                logging.error(f"Benchmark build script not found: {new_benchmark_build}")
                sys.exit(1)

            if not (ct_change_build(new_benchmark_build, each_ct_config)):
                logging.warning(f"No changes made to build script for {benchmark}")
                logging.warning(f"Please ensure {{CT_CONFIGURATION}} is present in the build script.")
        
        if (strategy, benchmark) in mapping:
            logging.error(f"Duplicate strategy-benchmark pair found: {(strategy, benchmark)}")
            logging.error("This should never happen. Exiting.")
            sys.exit(1)

        mapping[(strategy, benchmark)] = new_benchmarks
    return (mapping, tot_cts)


# DEBUG
if __name__ == "__main__":
    strategy = "randomnaive"
    experiment_path = "/tmp/experiment-data/test3"
    project_root = "/home/tahmeed/PhD/Projects/FuzzBenchPlusPlus"
    benchmarks = ["libxml2_xmllint"]
    apply_ct_strategy(strategy, project_root, benchmarks)