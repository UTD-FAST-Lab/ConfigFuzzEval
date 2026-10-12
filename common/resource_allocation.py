import os, sys
import subprocess
import platform
from math import ceil
from color_logger import get_logger
logging = get_logger(__name__)

def is_cpu_heterogeneous():
    system = platform.system()
    if system == "Linux":
        try:
            output = subprocess.check_output("lscpu", shell=True, text=True)
            # Intel hybrid CPUs usually show "Hybrid" in lscpu output
            if "Hybrid" in output:
                return True

            # fallback: check if multiple different model names are reported
            cpuinfo = subprocess.check_output("cat /proc/cpuinfo", shell=True, text=True)
            model_names = {line.split(":")[1].strip()
                           for line in cpuinfo.splitlines() if "model name" in line}
            return len(model_names) > 1
        except Exception:
            return False
    
    else:
        logging.error(f"Non-Linux OS detected: {system}. Not supported")
        sys.exit(1)


def check_core_allocation_feasibility(cores_to_use):
    total_cores = os.cpu_count()
    if cores_to_use > total_cores:
        logging.error(f"Requested {cores_to_use} cores, but only {total_cores} available.")
        sys.exit(1)


def needs_serial_execution(total_experiments, cores_to_use):
    if total_experiments > cores_to_use:
        return ceil(total_experiments / cores_to_use)
    else:
        return 0


def allocate_cpu_resources(experiment_state):
    # Check CPU
    if is_cpu_heterogeneous():
        logging.warning("Your CPU has a heterogeneous (big.LITTLE / P+E core) design.")
        logging.warning("This will likely lead to unfair resource allocation.")
    else:
        logging.info("Your CPU has a homogeneous design (all cores equal).")

    check_core_allocation_feasibility(experiment_state["cores_to_use"])
    
    # Set core start counter. We use the last n cores, or n cores from first_core when
    # it is set (e.g. to run next to another experiment that uses the last cores).
    # A trial on core c runs on CPUs c-1 and c, so the first core must be at least 1.
    first_core = experiment_state.get("first_core")
    if first_core is None:
        core_start = os.cpu_count() - experiment_state["cores_to_use"]
    else:
        core_start = first_core
        if core_start < 1 or core_start + experiment_state["cores_to_use"] > os.cpu_count():
            logging.error(f"first_core {first_core} with cores_to_use {experiment_state['cores_to_use']} "
                          f"does not fit cores 1 to {os.cpu_count() - 1}.")
            sys.exit(1)
    core_end = core_start + experiment_state["cores_to_use"] - 1
    
    logging.info(f"Allocating cores {core_start} to {core_end} for experiments")
    
    # Check if serial execution is necessary
    serial_execs = needs_serial_execution(
                        len(experiment_state.get("run_pairs", experiment_state["fuzzer_benchmark_pairs"])) * 
                        experiment_state["trials"],
                        experiment_state["cores_to_use"]
                        )
    
    if serial_execs:
        logging.warning("Number of experiments exceeds available cores.")
        
        if experiment_state["allow_serial_execution"]:
            logging.warning("Proceeding with serial execution as allowed by configuration.")
            time_required_hours = serial_execs * experiment_state["max_total_time"] / 3600
            logging.info(f"Experiments will require roughly {time_required_hours} hours in total.")

            experiment_state["estimated_tot_time_hours"] = time_required_hours
            experiment_state["cores_used_at_a_time"] = experiment_state["cores_to_use"]

        else:
            logging.error("Set 'allow_serial_execution' to True in configuration to allow this, or reduce experiments.")
            sys.exit(1)
    
    else:
        logging.info("No serial execution required.")
        experiment_state["estimated_tot_time_hours"] = \
            experiment_state["max_total_time"] / 3600
        experiment_state["cores_used_at_a_time"] = \
            len(experiment_state.get("run_pairs", experiment_state["fuzzer_benchmark_pairs"])) * experiment_state["trials"]

    experiment_state["serial_executions"] = serial_execs
    experiment_state["cores_range"] = (core_start, core_end)

    return experiment_state


def allocate_memory_resources(experiment_state):
    # Get memory per experiment (assumed to be in MB)
    memory_per_experiment_mb = experiment_state.get("experiment_memory", 3072)  # Default 3GB

    # Convert to GB for storage
    memory_per_experiment_gb = memory_per_experiment_mb / 1024
    
    # Calculate total memory needed at a time
    tot_exp_in_parallel = experiment_state["cores_used_at_a_time"]
    total_memory_needed_gb = tot_exp_in_parallel * memory_per_experiment_gb

    logging.info(f"Attempting to allocate {memory_per_experiment_gb:.2f} GB memory for each experiment")
    logging.info(f"Total memory needed at a time: {total_memory_needed_gb:.2f} GB")

    # Check available system memory (Linux only)
    try:
        with open('/proc/meminfo', 'r') as f:
            meminfo = f.read()
            total_memory_kb = int([line.split()[1] for line in meminfo.split('\n') if line.startswith('MemTotal:')][0])
            available_memory_gb = total_memory_kb / (1024 * 1024)  # Convert KB to GB
            
            logging.info(f"System has {available_memory_gb:.2f} GB total memory")
            
            if total_memory_needed_gb > available_memory_gb:
                logging.error(f"Memory requirement ({total_memory_needed_gb:.2f} GB) exceeds available system memory ({available_memory_gb:.2f} GB)")
                logging.error("Reduce 'experiment_memory' or 'cores_to_use'.")

            else:
                logging.info("Memory allocation is feasible")
                
    except Exception as e:
        logging.error(f"Could not determine system memory: {e}")
        print(f"Error details: {e}")
        sys.exit(1)

    # Store memory allocation information in experiment_state
    experiment_state["memory_per_experiment_gb"] = memory_per_experiment_gb
    experiment_state["total_memory_needed_gb"] = total_memory_needed_gb
    
    
    return experiment_state


def allocate_resources(experiment_state):
    experiment_state = allocate_cpu_resources(experiment_state)
    experiment_state = allocate_memory_resources(experiment_state)
    return experiment_state