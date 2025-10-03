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
                        "--build-arg", "FUZZER_FLAGS=-fsanitize=fuzzer,address",
                    "--build-arg", "CFLAGS=-fprofile-instr-generate -fcoverage-mapping",
                    "--no-cache"
                ], check=True, stdout=lf, stderr=lf)
            else:
                # Extract environment variables from fuzzer image
                env_vars = {}
                try:
                    # Get environment variables from the fuzzer image
                    result = subprocess.run([
                        "docker", "run", "--rm", f"fbpp/fuzzer:{fuzzer}",
                        "env"
                    ], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    
                    # Parse environment variables
                    for line in result.stdout.strip().split('\n'):
                        if '=' in line:
                            key, value = line.split('=', 1)
                            if key.startswith('FUZZER_'):
                                env_vars[key] = value
                                lf.write(f"[INFO] Found {key}={value}\n")
                except subprocess.CalledProcessError as e:
                    lf.write(f"[WARNING] Could not extract env vars from fuzzer image: {e}\n")
                
                # Build benchmark with environment variables as build args
                build_args = [
                    "docker", "build",
                    "-t", f"fbpp/benchmark:{benchmark_pair_name}",
                    "-f", benchmark_dockerfile,
                    benchmark_dir,
                    "--build-arg", f"parent_image=fbpp/fuzzer:{fuzzer}",
                    "--no-cache"
                ]
                
                # Add environment variables as build arguments
                for key, value in env_vars.items():
                    build_args.extend(["--build-arg", f"{key}={value}"])
                
                subprocess.run(build_args, check=True, stdout=lf, stderr=lf)

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
