import os
import subprocess
import sys
from shutil import copytree, copyfile
from color_logger import get_logger

logging = get_logger(__name__)


def build_runner_image(runner_image_path, project_root, runtime):
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
        "--build-arg",
        f"RUNTIME={runtime}",
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
        f"RUNTIME={runtime}",
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

    # Find the fuzzer directory in the project
    fuzzer_dir = os.path.join(project_root, "fuzzers", fuzzer_name)
    fuzzer_dockerfile = os.path.join(fuzzer_dir, "builder.Dockerfile")

    if not os.path.exists(fuzzer_dockerfile):
        print(f"[ERROR] Fuzzer Dockerfile {fuzzer_dockerfile} does not exist.")
        return False

    print(f"[INFO] Building fuzzer: {fuzzer_name}")
    try:
        subprocess.run([
            "docker",
            "build",
            "-t",
            f"fbpp/fuzzer:{fuzzer_name}",
            "-f",
            fuzzer_dockerfile,
            fuzzer_dir,
            "--build-arg",
            "parent_image=fbpp/base",
            "--no-cache"
        ], check=True)

        subprocess.run([
            "docker",
            "run",
            "--rm",
            "-v",
            f"{fuzzer_path}:/fuzzer_output",
            f"fbpp/fuzzer:{fuzzer_name}"
        ], check=True)

    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Failed while building or running {fuzzer_name}.")
        print(f"[ERROR] Command: {e.cmd}")
        print(f"[ERROR] Return code: {e.returncode}")
        return False

    # copyfile(runner_src, runner_dest)
    print(f"[SUCCESS] Built and ran fuzzer: {fuzzer_name}")
    return True


# Build both fuzzing and coverage binaries
def build_benchmark(fuzzer, benchmark_name, experiment_path, project_root):
    benchmark_path = os.path.join(experiment_path, "benchmarks")
    
    if not os.path.exists(benchmark_path):
        os.makedirs(benchmark_path, exist_ok=True)
    else:
        print(f"Benchmark path {benchmark_path} already exists.")

    # Find the benchmark directory in the project
    benchmark_dir = os.path.join(project_root, "benchmarks", benchmark_name)
    benchmark_dockerfile = os.path.join(benchmark_dir, "builder.Dockerfile")

    if not os.path.exists(benchmark_dockerfile):
        print(f"[ERROR] Benchmark Dockerfile {benchmark_dockerfile} does not exist.")
        return False

    benchmark_pair_name = f"{fuzzer}_{benchmark_name}"
    benchmark_pair_path = os.path.join(benchmark_path, benchmark_pair_name)
    if os.path.exists(benchmark_pair_path):
        print(f"[ERROR] Benchmark {benchmark_pair_name} already exists. This should never happen")
        sys.exit(1)

    os.makedirs(benchmark_pair_path, exist_ok=True)
    

    print(f"[INFO] Building benchmark: {benchmark_pair_name}")
    
    try:
        if fuzzer == "coverage":
            subprocess.run([
                "docker",
                "build",
                "-t",
                f"fbpp/benchmark:{benchmark_pair_name}",
                "-f",
                benchmark_dockerfile,
                benchmark_dir,
                "--build-arg",
                f"parent_image=fbpp/base",
                "--build-arg",
                f"CC=clang",
                "--build-arg",
                f"CXX=clang++",
                "--build-arg",
                f"CFLAGS=-fprofile-instr-generate -fcoverage-mapping",
                "--no-cache"
            ], check=True)
        
        else:
            subprocess.run([
                "docker",
                "build",
                "-t",
                f"fbpp/benchmark:{benchmark_pair_name}",
                "-f",
                benchmark_dockerfile,
                benchmark_dir,
                "--build-arg",
                f"parent_image=fbpp/fuzzer:{fuzzer}",
                "--no-cache"
            ], check=True)
            
        subprocess.run([
            "docker",
            "run",
            "--rm",
            "-v",
            f"{benchmark_pair_path}:/benchmark_out_dir",
            f"fbpp/benchmark:{benchmark_pair_name}"
        ], check=True)

    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Failed while building {benchmark_name}.")
        print(f"[ERROR] Command: {e.cmd}")
        print(f"[ERROR] Return code: {e.returncode}")
        return False

    print(f"[SUCCESS] Built benchmark: {benchmark_name}")
    return True


def run_benchmark(fuzzer, benchmark, coverage_binary, report_path, 
                    runtime, trials, trial_id, experiment_path, core_id, 
                    data_storage, memory_limit):
    # setup
    individual_data_storage = os.path.join(data_storage, f"{fuzzer}_{benchmark}_trial{trial_id}")
    os.makedirs(individual_data_storage, exist_ok=True)
    
    benchmark_location = os.path.join(experiment_path, "benchmarks", f"{fuzzer}_{benchmark}")
    fuzzer_location = os.path.join(experiment_path, "fuzzers", f"{fuzzer}")

    # TODO: This MUST be changed to run in parallel, also should be logged to a text file. Maybe the whole function should run in parallel since we have core_id
    
    try:
        # Run the benchmark
        subprocess.run([
            "docker",
            "run",
            "--rm",
            f"--cpuset-cpus={core_id}-{core_id+1}",
            "-m", f"{memory_limit}g",
            f"--memory-swap={memory_limit}g",
            "-v", f"{benchmark_location}:/benchmark",
            "-v", f"{fuzzer_location}:/fuzzer",
            "-v", f"{individual_data_storage}:/fuzzer_output",
            "fbpp/runner"
        ], check=True)
        
        # Time to calculate coverage
        coverage_binary_location = os.path.join(experiment_path, "benchmarks", f"coverage_{benchmark}")
        subprocess.run([
            "docker",
            "run",
            "--rm",
            f"--cpuset-cpus={core_id}-{core_id+1}",
            "-m", f"{memory_limit}g",
            f"--memory-swap={memory_limit}g",
            "-v", f"{coverage_binary_location}:/benchmark",
            "-v", f"{fuzzer_location}:/fuzzer",
            "-v", f"{individual_data_storage}:/fuzzer_output",
            "fbpp/runner-coverage"
        ], check=True)
        
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Failed while running {fuzzer} on {benchmark}.")
        print(f"[ERROR] Command: {e.cmd}")
        print(f"[ERROR] Return code: {e.returncode}")
