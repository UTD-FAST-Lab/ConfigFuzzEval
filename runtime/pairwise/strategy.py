"""pairwise (2W): a 2-way covering array over the run-time options.

Every valid pair of values of every two options appears together in at least one
configuration (ConfigFuzz's Baseline-2-way, TOSEM 2023; VAFuzz's 2W, ICSE 2026).
ConfigFuzz used NIST ACTS; this is a greedy (AETG-style) generator, so array sizes
differ, but every valid pair is covered.
"""

import itertools
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from rt_common import Grammar  # noqa: E402


def covering_array(g):
    """Configurations (dicts of value positions) covering every valid pair."""
    n = len(g.options)
    # Every valid pair (option i = value vi, option j = value vj), i < j, by position.
    uncovered = set()
    for i, j in itertools.combinations(range(n), 2):
        for vi in range(len(g.values[i])):
            for vj in range(len(g.values[j])):
                if g.valid({i: g.values[i][vi], j: g.values[j][vj]}):
                    uncovered.add((i, vi, j, vj))
    configs = []
    while uncovered:
        # Start from an uncovered pair, then give every other option the value that
        # covers the most uncovered pairs (ties broken randomly).
        i, vi, j, vj = g.rng.choice(sorted(uncovered))
        chosen = {i: vi, j: vj}
        rest = [k for k in range(n) if k not in chosen]
        g.rng.shuffle(rest)
        for k in rest:
            best, best_gain = [], -1
            for vk in range(len(g.values[k])):
                trial = {o: g.values[o][v] for o, v in chosen.items()}
                trial[k] = g.values[k][vk]
                if not g.valid(trial):
                    continue
                gain = sum(1 for o, v in chosen.items()
                           if (min(o, k), v if o < k else vk, max(o, k), vk if o < k else v) in uncovered)
                if gain > best_gain:
                    best, best_gain = [vk], gain
                elif gain == best_gain:
                    best.append(vk)
            chosen[k] = g.rng.choice(best) if best else 0
        covered = {(a, chosen[a], b, chosen[b]) for a, b in itertools.combinations(range(n), 2)}
        config_ok = g.valid({k: g.values[k][v] for k, v in chosen.items()})
        if not config_ok or not covered & uncovered:
            uncovered.discard((i, vi, j, vj))  # pair cannot be completed into a valid config
            continue
        uncovered -= covered
        configs.append({k: g.values[k][v] for k, v in chosen.items()})
    return configs


def request_configurations(grammar, rng):
    g = Grammar(grammar, rng)
    return [g.args(c) for c in covering_array(g)]
