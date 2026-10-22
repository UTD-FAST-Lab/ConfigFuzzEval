"""Generates run-time configurations for --runtime-strategy (see runtime/).

For every non-default runtime strategy x benchmark x trial, reads the benchmark's
rt_grammar.json, asks runtime/<strategy>/strategy.py for configurations, shuffles
them and writes

    <experiment>/rt_configs/<strategy>/<benchmark>/trial_<k>.json

The file is shared by every supported fuzzer (runtime/supported_fuzzers.json) and
every compile-time variant of the benchmark, so they all fuzz the same
configurations in the same order. The seed depends on the experiment's
random_seed, the strategy, the benchmark and the trial: every trial gets its own
order, and a run with the same random_seed gets the same configurations.
"""

import hashlib
import importlib.util
import json
import os
import random

from color_logger import get_logger

logging = get_logger(__name__)


def load_supported_fuzzers(project_root):
    with open(os.path.join(project_root, "runtime", "supported_fuzzers.json")) as f:
        return {k: v for k, v in json.load(f).items() if not k.startswith("_")}


def load_strategy(project_root, strategy):
    path = os.path.join(project_root, "runtime", strategy, "strategy.py")
    spec = importlib.util.spec_from_file_location(f"rt_strategy_{strategy}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def trial_seed(random_seed, strategy, benchmark, trial):
    if random_seed is None:
        return random.SystemRandom().randrange(2 ** 32)
    key = f"{random_seed}:{strategy}:{benchmark}:{trial}".encode()
    return int.from_bytes(hashlib.sha256(key).digest()[:4], "big")


def generate_rt_configs(strategies, benchmarks, trials, experiment_path, project_root, random_seed):
    """Writes the configuration files; returns {(strategy, benchmark, trial): path}."""
    files = {}
    for strategy in strategies:
        if strategy == "default":
            continue
        module = load_strategy(project_root, strategy)
        for benchmark in benchmarks:
            with open(os.path.join(project_root, "benchmarks", benchmark, "rt_grammar.json")) as f:
                grammar = json.load(f)
            out_dir = os.path.join(experiment_path, "rt_configs", strategy, benchmark)
            os.makedirs(out_dir, exist_ok=True)
            for trial in range(trials):
                seed = trial_seed(random_seed, strategy, benchmark, trial)
                rng = random.Random(seed)
                configs = module.request_configurations(grammar, rng)
                rng.shuffle(configs)
                path = os.path.join(out_dir, f"trial_{trial}.json")
                with open(path, "w") as f:
                    json.dump({"strategy": strategy, "benchmark": benchmark, "trial": trial,
                               "seed": seed, "total_generated": len(configs),
                               "configs": configs}, f, indent=1)
                files[(strategy, benchmark, trial)] = path
            logging.info(f"Runtime strategy {strategy}: {len(configs)} configurations for {benchmark}")
    return files
