"""The strategies' earlier names (manual, maximum, minimum, randomsmart, random) still work in experiment files."""
import os
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "common"))

import experiment_plan
from strategy_names import ALIASES


def test_every_strategy_is_a_folder_and_no_alias_is():
    for kind, folder in (("compiletime", "compiletime"), ("runtime_strategy", "runtime")):
        for old, new in ALIASES[kind].items():
            assert os.path.isfile(os.path.join(ROOT, folder, new, "strategy.py")), new
            assert not os.path.exists(os.path.join(ROOT, folder, old)), old


def test_earlier_names_are_replaced():
    groups = [{"fuzzers": ["aflplusplus"], "benchmarks": ["xz_xz"],
               "compiletime": ["default", "maximum", "minimum", "manual", "randomsmart", "mostenabled"],
               "runtime_strategy": ["random", "smartrandom", "pairwise"]}]
    runs = experiment_plan.expand_groups(groups, {"trials": 1, "max_total_time": 60})
    assert sorted({r["compiletime"] for r in runs}) == ["default", "handselected", "mostdisabled", "mostenabled",
                                                       "smartrandom"]
    assert sorted({r["runtime_strategy"] for r in runs}) == ["pairwise", "smartrandom"]
    # a name given twice, once by its earlier name, is one run
    assert len(runs) == 5 * 2
