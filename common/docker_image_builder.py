import os
import subprocess
import sys


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


def build_fuzzer(fuzzer_name, experiment_path, project_root):
    fuzzer_path = os.path.join(experiment_path, "fuzzers")
    
    if not os.path.exists(fuzzer_path):
        os.makedirs(fuzzer_path, exist_ok=True)
    else:
        print(f"Fuzzer path {fuzzer_path} already exists.")
    
    # Find the fuzzer directory in the project
    fuzzer_dir = os.path.join(project_root, "fuzzers", fuzzer_name)
    
    # Build the fuzzer using builder.Dockerfile
    fuzzer_dockerfile = os.path.join(fuzzer_dir, "builder.Dockerfile")
    if not os.path.exists(fuzzer_dockerfile):
        print(f"Fuzzer Dockerfile {fuzzer_dockerfile} does not exist.")
        sys.exit(1)

    print(f"Building fuzzer: {fuzzer_name}")
    subprocess.run([
        "docker", 
        "build", 
        "-t", 
        f"fbpp/fuzzer:{fuzzer_name}", 
        "-f", 
        fuzzer_dockerfile, 
        fuzzer_dir,
        "--build-arg",
        f"parent_image=fbpp/base",
    ], check=True)
    
    subprocess.run([
        "docker", 
        "run", 
        "--rm", 
        "-v", 
        f"{fuzzer_path}:/fuzzer_output", 
        f"fbpp/fuzzer:{fuzzer_name}"
    ], check=True)



def build_benchmark(benchmark_name, experiment_path, project_root):
    pass