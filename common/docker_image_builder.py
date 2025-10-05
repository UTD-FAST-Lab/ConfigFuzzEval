import os
import subprocess
import sys
from shutil import copytree, copyfile
from color_logger import get_logger

logging = get_logger(__name__)


def build_runner_image(runner_image_path, project_root):
    runner_image_path = os.path.join(project_root, runner_image_path)
    runner_image_name = "fbpp/runner"

    # Validate runner image path
    if not os.path.exists(runner_image_path):
        return 1

    # Build runner image
    subprocess.run([
        "docker",
        "build",
        "-t",
        runner_image_name,
        runner_image_path,
        "--no-cache"
    ], check=True)
    
    # Build coverage runner image
    subprocess.run([
        "docker",
        "build",
        "-t",
        f"{runner_image_name}-coverage",
        "--build-arg",
        f"COVERAGE=true",
        runner_image_path,
        "--no-cache"
    ], check=True)

    return 0



def build_base_image(base_image_path, project_root):
    base_image_path = os.path.join(project_root, base_image_path)
    base_image_name = "fbpp/base"
    
    # Validate base image path
    if not os.path.exists(base_image_path):
        return 1
    
    # Build base image
    subprocess.run([
        "docker", 
        "build", 
        "-t", 
        base_image_name, 
        base_image_path
        ], check=True)


# Build fuzzer images based on fuzzer builder.Dockerfile
def build_fuzzer(fuzzer_name, experiment_path, project_root):
    fuzzer_path = os.path.join(experiment_path, "fuzzers")
    os.makedirs(fuzzer_path, exist_ok=True)

    # Log file per fuzzer
    log_file = os.path.join(fuzzer_path, f"{fuzzer_name}_build.log")
    with open(log_file, "w") as lf:
        # Find the fuzzer directory in the project
        fuzzer_dir = os.path.join(project_root, "fuzzers", fuzzer_name)
        fuzzer_dockerfile = os.path.join(fuzzer_dir, "builder.Dockerfile")

        if not os.path.exists(fuzzer_dockerfile):
            msg = f"[ERROR] Fuzzer Dockerfile {fuzzer_dockerfile} does not exist.\n"
            lf.write(msg)
            logging.error(msg.strip())
            return False

        msg = f"[INFO] Building fuzzer: {fuzzer_name}\n"
        lf.write(msg)
        logging.info(msg.strip())

        try:
            # Check if build already exists
            
            
            existing_image = f"fbpp/fuzzer:{fuzzer_name}"
            result = subprocess.run(["docker", "images", "-q", existing_image], check=True, stdout=subprocess.PIPE)
            if result.stdout:
                msg = f"[WARNING] Fuzzer image {existing_image} already exists. Skipping build.\n"
                lf.write(msg)
                logging.warning(f"Fuzzer image {existing_image} already exists. Skipping build.")
                subprocess.run([
                    "docker", "run",
                    "--rm",
                    "-v", f"{fuzzer_path}:/fuzzer_output",
                    f"fbpp/fuzzer:{fuzzer_name}"
                ], check=True, stdout=lf, stderr=lf)
            else:
                subprocess.run([
                    "docker", "build",
                    "-t", f"fbpp/fuzzer:{fuzzer_name}",
                    "-f", fuzzer_dockerfile,
                    fuzzer_dir,
                    "--build-arg", "parent_image=fbpp/base",
                    "--no-cache"
                ], check=True, stdout=lf, stderr=lf)

                subprocess.run([
                    "docker", "run",
                    "--rm",
                    "-v", f"{fuzzer_path}:/fuzzer_output",
                    f"fbpp/fuzzer:{fuzzer_name}"
                ], check=True, stdout=lf, stderr=lf)

        except subprocess.CalledProcessError as e:
            lf.write(f"[ERROR] Failed while building or running {fuzzer_name}.\n")
            lf.write(f"[ERROR] Command: {e.cmd}\n")
            lf.write(f"[ERROR] Return code: {e.returncode}\n")

            logging.error(f"Failed while building {fuzzer_name}. See {log_file} for details.")
            return False

        lf.write(f"[SUCCESS] Built and ran fuzzer: {fuzzer_name}\n")

    logging.success(f"Built and ran fuzzer: {fuzzer_name} (logs: {log_file})")
    return True


# Build both fuzzing and coverage binaries
def build_benchmark(fuzzer, benchmark_name, experiment_path, project_root):
    benchmark_path = os.path.join(experiment_path, "benchmarks")
    os.makedirs(benchmark_path, exist_ok=True)

    # Log file per fuzzer/benchmark pair
    benchmark_pair_name = f"{fuzzer}_{benchmark_name}"
    log_file = os.path.join(benchmark_path, f"{benchmark_pair_name}_build.log")

    with open(log_file, "w") as lf:
        # Find the benchmark directory in the project
        benchmark_dir = os.path.join(project_root, "benchmarks", benchmark_name)
        benchmark_dockerfile = os.path.join(benchmark_dir, "builder.Dockerfile")

        if not os.path.exists(benchmark_dockerfile):
            msg = f"[ERROR] Benchmark Dockerfile {benchmark_dockerfile} does not exist.\n"
            lf.write(msg)
            logging.error(msg.strip())
            return False

        benchmark_pair_path = os.path.join(benchmark_path, benchmark_pair_name)
        if os.path.exists(benchmark_pair_path):
            msg = f"[ERROR] Benchmark {benchmark_pair_name} already exists. This should never happen\n"
            lf.write(msg)
            logging.error(msg.strip())
            sys.exit(1)

        os.makedirs(benchmark_pair_path, exist_ok=True)

        msg = f"[INFO] Building benchmark: {benchmark_pair_name}\n"
        lf.write(msg)
        logging.info(msg.strip())

        try:
            if fuzzer == "coverage":
                subprocess.run([
                    "docker", "build",
                    "-t", f"fbpp/benchmark:{benchmark_pair_name}",
                    "-f", benchmark_dockerfile,
                    benchmark_dir,
                    "--build-arg", "parent_image=fbpp/base",
                    "--build-arg", "CC=clang",
                    "--build-arg", "CXX=clang++",
                    "--build-arg", "CFLAGS=-fprofile-instr-generate -fcoverage-mapping",
                    "--no-cache"
                ], check=True, stdout=lf, stderr=lf)
            else:
                subprocess.run([
                    "docker", "build",
                    "-t", f"fbpp/benchmark:{benchmark_pair_name}",
                    "-f", benchmark_dockerfile,
                    benchmark_dir,
                    "--build-arg", f"parent_image=fbpp/fuzzer:{fuzzer}",
                    "--no-cache"
                ], check=True, stdout=lf, stderr=lf)

            subprocess.run([
                "docker", "run",
                "--rm",
                "-v", f"{benchmark_pair_path}:/benchmark_out_dir",
                f"fbpp/benchmark:{benchmark_pair_name}"
            ], check=True, stdout=lf, stderr=lf)

        except subprocess.CalledProcessError as e:
            lf.write(f"[ERROR] Failed while building {benchmark_name}.\n")
            lf.write(f"[ERROR] Command: {e.cmd}\n")
            lf.write(f"[ERROR] Return code: {e.returncode}\n")

            return False

        lf.write(f"[SUCCESS] Built benchmark: {benchmark_name}\n")

    # logging.success(f"Built benchmark: {benchmark_pair_name} (logs: {log_file})")
    return True

# Build bug triaging tools images based on bug-triaging <tool>/Dockerfile
def build_bug_triager(bug_triager_name, experiment_path, project_root):
    triager_path = os.path.join(experiment_path, "bug-triaging", bug_triager_name)
    os.makedirs(triager_path, exist_ok=True)

    # Log file per Triager
    log_file = os.path.join(triager_path, f"{bug_triager_name}_build.log")
    with open(log_file, "w") as lf:
        # Find the bug triaging tool directory in the project
        btt_dir = os.path.join(project_root, "bug-triaging", bug_triager_name)
        btt_dockerfile = os.path.join(btt_dir, "Dockerfile")

        if not os.path.exists(btt_dockerfile):
            msg = f"[ERROR] Bug-Triaging Dockerfile {btt_dockerfile} does not exist.\n"
            lf.write(msg)
            logging.error(msg.strip())
            return False

        msg = f"[INFO] Building Triaging Tool: {bug_triager_name}\n"
        lf.write(msg)
        logging.info(msg.strip())

        try:
            # Check if build already exists
            
            
            existing_image = f"fbpp/bug-triaging:{bug_triager_name}"
            result = subprocess.run(["docker", "images", "-q", existing_image], check=True, stdout=subprocess.PIPE)
            if result.stdout:
                msg = f"[WARNING] Bug-Triaging image {existing_image} already exists. Skipping build.\n"
                lf.write(msg)
                logging.warning(f"Bug-Triaging image {existing_image} already exists. Skipping build.")
                subprocess.run([
                    "docker", "run",
                    "--rm",
                    "-e", "TEST_TRIAGE=1",
                    "-v", f"{triager_path}:/triaging_output",
                    f"fbpp/bug-triaging:{bug_triager_name}"
                ], check=True, stdout=lf, stderr=lf)
            else:
                subprocess.run([
                    "docker", "build",
                    "-t", f"fbpp/bug-triaging:{bug_triager_name}",
                    "-f", btt_dockerfile,
                    btt_dir,
                    "--no-cache"
                ], check=True, stdout=lf, stderr=lf)

                subprocess.run([
                    "docker", "run",
                    "--rm",
                    "-e", "TEST_TRIAGE=1",
                    "-v", f"{triager_path}:/triaging_output",
                    f"fbpp/bug-triaging:{bug_triager_name}"
                ], check=True, stdout=lf, stderr=lf)

        except subprocess.CalledProcessError as e:
            lf.write(f"[ERROR] Failed while building or running {bug_triager_name}.\n")
            lf.write(f"[ERROR] Command: {e.cmd}\n")
            lf.write(f"[ERROR] Return code: {e.returncode}\n")

            logging.error(f"Failed while building {bug_triager_name}. See {log_file} for details.")
            return False

        lf.write(f"[SUCCESS] Built and ran bug-triaging tool: {bug_triager_name}\n")

    logging.success(f"Built and ran bug-triaging tool: {bug_triager_name} (logs: {log_file})")
    return True


def run_benchmark(fuzzer, benchmark, coverage_binary, report_path, 
                  runtime, trials, trial_id, experiment_path, core_id, 
                  data_storage, memory_limit, tot_cts_count):
    # setup
    individual_data_storage = os.path.join(data_storage, f"{fuzzer}_{benchmark}_trial_{trial_id}")
    os.makedirs(individual_data_storage, exist_ok=True)
    
    actual_runtime = runtime // tot_cts_count if tot_cts_count > 0 else runtime
    print(f"Total CTs: {tot_cts_count}, Adjusted runtime per CT: {actual_runtime}")

    benchmark_location = os.path.join(experiment_path, "benchmarks", f"{fuzzer}_{benchmark}")
    fuzzer_location = os.path.join(experiment_path, "fuzzers", f"{fuzzer}")
    coverage_binary_location = os.path.join(experiment_path, "benchmarks", f"coverage_{benchmark}")

    # log file
    log_file = os.path.join(individual_data_storage, f"{fuzzer}_{benchmark}_trial{trial_id}.log")

    with open(log_file, "w") as lf:
        try:
            lf.write(f"[INFO] Running benchmark: {benchmark} with fuzzer: {fuzzer}, trial {trial_id}\n")
            logging.info(f"Running benchmark: {benchmark} with fuzzer: {fuzzer}, trial {trial_id}")

            # Run the benchmark
            subprocess.run([
                "docker", "run", "--rm",
                f"--cpuset-cpus={core_id}-{core_id+1}",
                "-m", f"{memory_limit}g",
                f"--memory-swap={memory_limit}g",
                "-e", f"RUNTIME={actual_runtime}",
                "-v", f"{benchmark_location}:/benchmark",
                "-v", f"{fuzzer_location}:/fuzzer",
                "-v", f"{individual_data_storage}:/fuzzer_output",
                "fbpp/runner"
            ], check=True, stdout=lf, stderr=lf)

            # Run coverage
            lf.write(f"[INFO] Calculating coverage for {benchmark}, trial {trial_id}\n")
            subprocess.run([
                "docker", "run", "--rm",
                f"--cpuset-cpus={core_id}-{core_id+1}",
                # "-m", f"{memory_limit}g",
                # f"--memory-swap={memory_limit}g",
                "-v", f"{coverage_binary_location}:/benchmark",
                "-v", f"{fuzzer_location}:/fuzzer",
                "-v", f"{individual_data_storage}:/fuzzer_output",
                "fbpp/runner-coverage"
            ], check=True, stdout=lf, stderr=lf)

        except subprocess.CalledProcessError as e:
            lf.write(f"[ERROR] Failed while running {fuzzer} on {benchmark}, trial {trial_id}\n")
            lf.write(f"[ERROR] Command: {e.cmd}\n")
            lf.write(f"[ERROR] Return code: {e.returncode}\n")
            logging.error(f"Failed: {fuzzer} on {benchmark}, trial {trial_id}. See {log_file} for details.")
            return False

    logging.success(f"Finished {fuzzer} on {benchmark}, trial {trial_id} (logs: {log_file})")
    return True


def run_triaging(triager, fuzzer, benchmark, trials,
                 experiment_path, core_id, data_storage, memory_limit):
    """
    Runs the triager for all trials of a given fuzzer-benchmark pair,
    pooling all crashes into a single output folder.
    """

    # --- Shared output directory for all trials ---
    triager_base_path = os.path.join(experiment_path, "bug-triaging", triager)
    triager_output_base = os.path.join(triager_base_path, "output")
    pooled_output_name = f"{fuzzer}_{benchmark}"
    trial_output_path = os.path.join(triager_output_base, pooled_output_name)
    os.makedirs(trial_output_path, exist_ok=True)

    # For backwards compatibility: keep logs directly under triager folder
    os.makedirs(triager_base_path, exist_ok=True)

    benchmark_location = os.path.join(experiment_path, "benchmarks", f"{fuzzer}_{benchmark}")
    fuzzer_location = os.path.join(experiment_path, "fuzzers", f"{fuzzer}")
    coverage_binary_location = os.path.join(experiment_path, "benchmarks", f"coverage_{benchmark}")

    # --- Loop over all trials ---
    for trial_id in range(trials):
        individual_data_storage = os.path.join(data_storage, f"{fuzzer}_{benchmark}_trial_{trial_id}")
        if not os.path.exists(individual_data_storage):
            msg = f"[ERROR] Data storage path {individual_data_storage} does not exist for trial {trial_id}. Skipping.\n"
            logging.error(msg.strip())
            continue

        # Per-trial log file in shared output folder
        log_file = os.path.join(
            trial_output_path,
            f"{fuzzer}_{benchmark}_{triager}_trial{trial_id}.log"
        )

        with open(log_file, "w") as lf:
            try:
                lf.write(f"[INFO] Triaging benchmark: {benchmark} with fuzzer: {fuzzer}, trial {trial_id} using {triager}\n")
                logging.info(f"Triaging benchmark: {benchmark} with fuzzer: {fuzzer}, trial {trial_id} using {triager}")

                # Mount trial-specific input, but shared output
                subprocess.run([
                    "docker", "run", "--rm",
                    f"--cpuset-cpus={core_id}-{core_id+1}",
                    "-m", f"{memory_limit}g",
                    f"--memory-swap={memory_limit}g",
                    "-v", f"{benchmark_location}:/benchmark",
                    "-v", f"{fuzzer_location}:/fuzzer",
                    "-v", f"{individual_data_storage}:/fuzzer_output",
                    "-v", f"{trial_output_path}:/triaging_output",
                    f"fbpp/bug-triaging:{triager}"
                ], check=True, stdout=lf, stderr=lf)

            except subprocess.CalledProcessError as e:
                lf.write(f"[ERROR] Failed while running {fuzzer} on {benchmark}, trial {trial_id} using {triager}\n")
                lf.write(f"[ERROR] Command: {e.cmd}\n")
                lf.write(f"[ERROR] Return code: {e.returncode}\n")
                logging.error(f"Failed Triaging for trial {trial_id}. See {log_file} for details.")
                continue

        logging.success(f"Finished triaging {fuzzer} on {benchmark}, trial {trial_id} using {triager} (log: {log_file})")

    logging.success(f"✅ All trials completed for {fuzzer} on {benchmark} using {triager}. Output pooled at {trial_output_path}")
    return True

