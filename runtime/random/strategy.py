"""random (Rand): 50 distinct random valid configurations (VAFuzz, ICSE 2026,
Section 4.1, which fixed the number at 50).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from rt_common import Grammar  # noqa: E402

from rt_common import distinct  # noqa: E402

COUNT = 50


def request_configurations(grammar, rng):
    g = Grammar(grammar, rng)
    configs = []
    for _ in range(COUNT * 20):  # small grammars may have fewer than 50 distinct configs
        configs = distinct(configs + [g.random_config()])
        if len(configs) == COUNT:
            break
    return [g.args(c) for c in configs]
