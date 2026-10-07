"""Shared code for run-time configuration strategies (runtime/<strategy>/strategy.py).

A strategy turns a benchmark's rt_grammar.json into a list of configurations,
each a list of command-line arguments built from the grammar's "cmdline"
($inopts -> the configuration's options, $INPUTFILE -> @@).

Option values follow the sampling setup of ConfigFuzz (Zhang et al., TOSEM 2023,
Section 5.1.2), also used for the sampling baselines of VAFuzz (ICSE 2026):
  - bool options: absent or present;
  - choice options: all choices, or a random 10 if there are more than 50;
  - intnum/realnum options: lower bound, upper bound and 8 random values between;
  - string options: not sampled;
  - every non-bool option can also be absent.
Choice values that are empty or contain whitespace are left out: the runner passes a
configuration to the fuzzer as one RUN_TARGET string, which would split them.
"""

import random
import re

ABSENT = None
MAX_CHOICES = 50
SAMPLED_CHOICES = 10
NUMERIC_BETWEEN = 8


def option_values(opt, rng):
    """The values sampled for one option, or None if the option is not sampled."""
    kind = opt["type"]
    if kind == "bool":
        return [False, True]
    if kind == "choice":
        choices = [c for c in opt["choices"] if str(c) and not any(ch.isspace() for ch in str(c))]
        if len(choices) > MAX_CHOICES:
            choices = rng.sample(choices, SAMPLED_CHOICES)
        return [ABSENT] + choices
    if kind in ("intnum", "realnum"):
        low, high = opt["range"]
        if kind == "intnum":
            between = rng.sample(range(low + 1, high), min(NUMERIC_BETWEEN, max(high - low - 1, 0)))
        else:
            between = [round(rng.uniform(low, high), 3) for _ in range(NUMERIC_BETWEEN)]
        return [ABSENT] + sorted(set([low, high] + between))
    return None  # string


def enabled(value):
    return value is not ABSENT and value is not False


class Grammar:
    """A run-time grammar with the sampled values of every option.

    Configurations are dicts {option index: value}; options missing from a
    (partial) configuration are undecided.
    """

    def __init__(self, grammar, rng):
        self.grammar = grammar
        self.rng = rng
        self.options = []
        self.values = []
        for opt in grammar["options"]:
            vals = option_values(opt, rng)
            if vals is not None:
                self.options.append(opt)
                self.values.append(vals)
        index = {o["opt"]: i for i, o in enumerate(self.options)}
        self.conflicts = [(index[a], index[b]) for a, b in grammar.get("conflict", [])
                          if a in index and b in index]
        self.depends = [(index[d["opt"]], [index[o] for o in d["on"] if o in index])
                        for d in grammar.get("depend", []) if d["opt"] in index]

    def valid(self, config):
        """Whether a (possibly partial) configuration violates no conflict or depend."""
        for a, b in self.conflicts:
            if a in config and b in config and enabled(config[a]) and enabled(config[b]):
                return False
        for opt, ons in self.depends:
            if opt in config and enabled(config[opt]):
                if any(o in config and not enabled(config[o]) for o in ons):
                    return False
        return True

    def random_config(self):
        """A random valid configuration (every option gets one of its values)."""
        for _ in range(100):
            config = {}
            order = list(range(len(self.options)))
            self.rng.shuffle(order)
            for k in order:
                candidates = list(self.values[k])
                self.rng.shuffle(candidates)
                config[k] = next((v for v in candidates if self.valid({**config, k: v})),
                                 self.values[k][0])
            if self.valid(config):
                return config
        return {k: self.values[k][0] for k in range(len(self.options))}  # everything off

    def args(self, config):
        """Command-line arguments of a configuration, from the grammar's cmdline."""
        opts = []
        for k in sorted(config):
            value, opt = config[k], self.options[k]
            if not enabled(value):
                continue
            if opt["type"] == "bool":
                opts.append(opt["opt"])
            elif self.grammar["connector"] == " ":
                opts += [opt["opt"], str(value)]
            elif re.fullmatch(r"-[A-Za-z0-9]", opt["opt"]):
                # Single-letter option: getopt takes its value attached ("-T2", "-WU");
                # "-T=2" would pass "=2" as the value, and an optional value must be attached.
                opts.append(f'{opt["opt"]}{value}')
            else:
                opts.append(f'{opt["opt"]}{self.grammar["connector"]}{value}')
        args = []
        for token in self.grammar["cmdline"].split():
            if token == "$inopts":
                args += opts
            elif token == "$INPUTFILE":
                args.append("@@")
            elif token != "$STDIN":
                args.append(token)
        return args


def hamming(a, b):
    """Number of options whose value differs between two configurations."""
    return sum(1 for k in a if a[k] != b.get(k))


def distinct(configs):
    """Configurations without duplicates, in order."""
    seen, out = set(), []
    for c in configs:
        key = tuple(sorted((k, repr(v)) for k, v in c.items()))
        if key not in seen:
            seen.add(key)
            out.append(c)
    return out
