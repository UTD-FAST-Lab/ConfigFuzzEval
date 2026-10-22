#!/usr/bin/env python3
"""Restrict a CarpetFuzz relation file to its N highest-coverage options.

CarpetFuzz's simplify_relationship.py, which its README recommends when there
are too many options for PICT's 6-wise combination (memory use explodes): each
option is dry-run alone on the first seed, and only the N options covering the
most tuples are kept. Unlike the original, conflicts and dependencies are kept
only if all their options are kept (PICT rejects constraints on unknown
parameters), and values come from our dict.json (see ../rank.py).

Run where the benchmark's carpetfuzz build is at /benchmark and the carpetfuzz
fuzzer at /fuzzer (generate.sh runs it in fbpp/runner, like a trial).
"""
import argparse
import json
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from rank import dry_run_coverage, render  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--relation", required=True)
    parser.add_argument("--dict", required=True)
    parser.add_argument("--number", type=int, default=50, help="options to keep (CarpetFuzz's default: 50)")
    parser.add_argument("--bindir", required=True)
    parser.add_argument("--seeddir", required=True)
    parser.add_argument("--showmap", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    with open(args.relation) as f:
        relation = json.load(f)["options"]
    with open(args.dict) as f:
        dictionary = json.load(f)
    seed = os.path.join(args.seeddir, sorted(os.listdir(args.seeddir))[0])

    rng = random.Random(0)
    coverage = {opt: dry_run_coverage(render(opt, dictionary, rng), args.bindir, seed, args.showmap)
                for opt in relation["total_options"]}
    failed = [o for o, t in coverage.items() if t is None]
    if len(failed) == len(coverage):
        sys.exit(f"[x] every dry run failed (e.g. {failed[0]}); check afl-showmap on this target")
    coverage = {o: t or 0 for o, t in coverage.items()}
    kept = sorted(coverage, key=coverage.get, reverse=True)[:args.number]
    kept_set = set(kept)

    def all_kept(*exprs):
        return all(o in kept_set for e in exprs for o in e.replace("&&", " ").replace("||", " ").split())

    restricted = {"options": {
        "total_options": [o for o in relation["total_options"] if o in kept_set],
        "conflict_options": [p for p in relation["conflict_options"] if all_kept(*p)],
        "dependent_options": {k: v for k, v in relation["dependent_options"].items() if all_kept(k, v)},
    }}
    with open(args.out, "w") as f:
        json.dump(restricted, f)
    print(f"[+] simplified {len(relation['total_options'])} -> {len(kept)} options "
          f"({len(restricted['options']['conflict_options'])} conflicts, "
          f"{len(restricted['options']['dependent_options'])} dependencies kept)")


if __name__ == "__main__":
    main()
