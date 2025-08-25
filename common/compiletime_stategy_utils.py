import os, sys, shutil
from common import utils
import itertools
import importlib
import traceback

def get_cts_names():
    """Return a list of compiletime strategy names."""
    ct_strat_dir = os.path.join(utils.ROOT_DIR, 'compiletime')
    ct_strats = []
    for strat in os.listdir(ct_strat_dir):
        print(f"Checking {strat}...")
        if not os.path.isfile(os.path.join(ct_strat_dir, strat, 'strategy.py')):
            continue
        ct_strats.append(strat)
    return ct_strats

def check_benchmark_ct_grammars():
    "Checks to see if all benchmarks have compile-time grammar"
    benchmark_strat_dir = os.path.join(utils.ROOT_DIR, 'benchmarks')
    print("Checking compile-time grammars for benchmarks...")
    
    for each_bench in os.listdir(benchmark_strat_dir):
        if each_bench.startswith('.'):
            continue
        
        print(f"Checking {each_bench}...")
        if not os.path.isfile(os.path.join(benchmark_strat_dir, each_bench, 'ct_grammar.json')):
            print(f"Benchmark {each_bench} does not have a compile-time grammar.")
            exit(1)
    print("All benchmarks have compile-time grammars.")

def generate_cts_benchmarks(ct_strats, benchmarks):
    """Generate compile-time strategy benchmarks."""
    all_cts_benchmarks = list(itertools.product(benchmarks, ct_strats))
    all_benchmark_names = []
    
    for cts_benchmark in all_cts_benchmarks:
        benchmark, ct_strat = cts_benchmark
        print(f"Generating benchmark {benchmark} with compile-time strategy {ct_strat}...")
        new_benchmark_names = generate_cts_benchmark(ct_strat, benchmark)
        all_benchmark_names.extend(new_benchmark_names)
    
    return all_benchmark_names
    
def generate_cts_benchmark(ct_strat, benchmark):
    """Generate a compile-time strategy benchmark."""
    benchmark_dir = os.path.join(utils.ROOT_DIR, 'benchmarks', benchmark)
    ct_strat_dir = os.path.join(utils.ROOT_DIR, 'compiletime', ct_strat)
    ct_grammar = os.path.join(benchmark_dir, 'ct_grammar.json')
    
    if not os.path.exists(benchmark_dir):
        print(f"Benchmark directory {benchmark_dir} does not exist.")
        exit(1)
    
    if not os.path.exists(ct_strat_dir):
        print(f"Compile-time strategy directory {ct_strat_dir} does not exist.")
        exit(1)
    
    # Generate configuration
    configurations = generate_ct_configs(ct_strat_dir, ct_grammar)
    
    for each in configurations:
        print(f"Generated configuration: {each}")
    
    # Generate benchmark with compile-time strategy
    new_benchmark_names = []
    for idx, ct_config in enumerate(configurations):
        new_bench_dir, new_benchmark_name = create_benchmark(benchmark, benchmark_dir, ct_strat, idx)
        inject_ct_config(new_bench_dir, ct_config)
        new_benchmark_names.append(new_benchmark_name)

    # using the compile-time strategy.
    print(f"Generated benchmark {benchmark} with compile-time strategy {ct_strat}.")  
    return new_benchmark_names 
    
def generate_ct_configs(ct_strat_dir, ct_grammar):
    """Generate configuration for compile-time strategy."""
    # Import the module
    if not validate_ct_strat(ct_strat_dir):
        print(f"Invalid compile-time strategy directory: {ct_strat_dir}")
        exit(1)
    
    strategy_path = os.path.join(ct_strat_dir, 'strategy.py')
    module_name = f"strategy_{os.path.basename(ct_strat_dir)}"
    spec = importlib.util.spec_from_file_location(module_name, strategy_path)
    if spec is None or spec.loader is None:
        print(f"Failed to create a module spec for {strategy_path}")
        traceback.print_exc()
        exit(1)

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    # Request configurations
    return module.request_configurations(ct_grammar)
    
def validate_ct_strat(ct_strat_dir):
    try:
        print(f"Validating compile-time strategy directory: {ct_strat_dir}")
        strategy_path = os.path.join(ct_strat_dir, 'strategy.py')
        
        if not os.path.isfile(strategy_path):
            print(f"No strategy.py found in {ct_strat_dir}")
            exit(1)

        # Make a unique module name
        module_name = f"strategy_{os.path.basename(ct_strat_dir)}"

        # Dynamically load the module
        spec = importlib.util.spec_from_file_location(module_name, strategy_path)
        if spec is None or spec.loader is None:
            print(f"Failed to create a module spec for {strategy_path}")
            traceback.print_exc()
            exit(1)

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)

    except Exception as e:
        print(f"Error importing strategy from {ct_strat_dir}: {e}")
        traceback.print_exc()
        exit(1)

    return True

def create_benchmark(benchmark, benchmark_dir, ct_strat, idx):
    """Create a benchmark with the given compile-time strategy and configuration."""
    print(f"Creating benchmark [{benchmark}] with compile-time strategy [{ct_strat}] (index {idx})...")

    benchmark_root = os.path.join(utils.ROOT_DIR, 'benchmarks')
    new_benchmark_name = f"cts_{benchmark}_{ct_strat}_{idx}"
    new_benchmark_dir = os.path.join(benchmark_root, new_benchmark_name)

    if os.path.exists(new_benchmark_dir):
        print(f"Benchmark directory {new_benchmark_dir} already exists. Deleting.")
        shutil.rmtree(new_benchmark_dir)
    
        
    shutil.copytree(benchmark_dir, new_benchmark_dir)
    print(f"Copied benchmark directory to {new_benchmark_dir}")
    return new_benchmark_dir, new_benchmark_name

def inject_ct_config(benchmark_dir, ct_config):
    """Inject the compile-time configuration into the build.sh script."""
    build_script = os.path.join(benchmark_dir, 'build.sh')
    
    if not os.path.isfile(build_script):
        print(f"Build script {build_script} does not exist.")
        exit(1)
    
    # Read the existing build script
    with open(build_script, 'r') as file:
        lines = file.readlines()
    
    # Replace {{CT_CONFIGuration}} with the actual configuration
    for i, line in enumerate(lines):
        if '{{CT_CONFIGURATION}}' in line:
            lines[i] = line.replace('{{CT_CONFIGURATION}}', str(ct_config))
            
    # Write the modified build script back
    with open(build_script, 'w') as file:
        file.writelines(lines)
    print(f"Injected compile-time configuration into {build_script}.")