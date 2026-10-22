"""mostdisabled (MD): one configuration with every option off, i.e. only the fixed
arguments of the grammar's cmdline (VAFuzz, ICSE 2026, Section 4.1).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from rt_common import Grammar  # noqa: E402


def request_configurations(grammar, rng):
    g = Grammar(grammar, rng)
    return [g.args({k: g.values[k][0] for k in range(len(g.options))})]
