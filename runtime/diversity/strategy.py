"""diversity (DB): 50 valid configurations that are as different from each other
as possible by Hamming distance (VAFuzz, ICSE 2026, Section 4.1; Pradhan et al.,
IOLTS 2005; Xiang et al., ICSE 2022).

Hamming distance = number of options whose value differs. From a pool of random
valid configurations, start with a random one, then repeatedly add the pool
configuration whose smallest distance to those already chosen is largest
(farthest-first), until 50 are chosen.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from rt_common import Grammar  # noqa: E402

from rt_common import distinct, hamming  # noqa: E402

COUNT = 50
POOL = 5000


def request_configurations(grammar, rng):
    g = Grammar(grammar, rng)
    pool = distinct([g.random_config() for _ in range(POOL)])
    chosen = [pool.pop(rng.randrange(len(pool)))]
    # Smallest distance from each pool configuration to the chosen set.
    nearest = [hamming(c, chosen[0]) for c in pool]
    while pool and len(chosen) < COUNT:
        best = max(nearest)
        i = rng.choice([j for j, d in enumerate(nearest) if d == best])
        chosen.append(pool.pop(i))
        nearest.pop(i)
        nearest = [min(d, hamming(c, chosen[-1])) for d, c in zip(nearest, pool)]
    return [g.args(c) for c in chosen]
