"""default: the normal run, one fixed command line from the benchmark's run_target.sh.

No configurations are generated; trials run the fuzzer once, as without a
runtime strategy.
"""


def request_configurations(grammar, rng):
    return []
