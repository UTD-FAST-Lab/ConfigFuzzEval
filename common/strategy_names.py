"""The sampling strategies' earlier names, still accepted in experiment files and on the command line.

The strategies are named as in the paper (Fig. 1): default, handselected, mostenabled, mostdisabled,
pairwise and smartrandom at compile time; default, mostenabled, mostdisabled, pairwise, smartrandom and
diversity at runtime. Each one is the folder of that name in compiletime/ or runtime/. Experiment
files written before the rename use the names on the left; result folders keep the name they were
run under.
"""

ALIASES = {
    "compiletime": {"manual": "handselected", "maximum": "mostenabled", "minimum": "mostdisabled",
                    "randomsmart": "smartrandom"},
    "runtime_strategy": {"random": "smartrandom"},
}


def canonical(kind, names):
    """names with every earlier name replaced by the current one; kind: compiletime or runtime_strategy."""
    aliases = ALIASES[kind]
    return list(dict.fromkeys(aliases.get(name, name) for name in names))


def renamed(kind, names):
    """[(earlier name, current name)] for the earlier names among names."""
    return [(name, ALIASES[kind][name]) for name in dict.fromkeys(names) if name in ALIASES[kind]]
