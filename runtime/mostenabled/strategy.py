"""mostenabled (ME): one configuration with as many options on as the grammar's
conflict/depend lists allow (VAFuzz, ICSE 2026, Section 4.1).

Options are turned on in grammar order, skipping any that would conflict with an
option already on; non-bool options take their first sampled value (first choice,
or the lower bound of a numeric range). Options whose required options ended up
off are turned off again. The result is the same for every trial.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from rt_common import Grammar  # noqa: E402


def request_configurations(grammar, rng):
    g = Grammar(grammar, rng)
    config = {}
    for k in range(len(g.options)):
        on = g.values[k][1]  # True for bool, first choice / lower bound otherwise
        config[k] = on if g.valid({**config, k: on}) else g.values[k][0]
    changed = True
    while changed:  # drop options whose requirements are off
        changed = False
        for opt, ons in g.depends:
            if config[opt] != g.values[opt][0] and any(config[o] == g.values[o][0] for o in ons):
                config[opt] = g.values[opt][0]
                changed = True
    return [g.args(config)]
