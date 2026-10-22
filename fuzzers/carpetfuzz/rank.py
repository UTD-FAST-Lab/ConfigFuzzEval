#!/usr/bin/env python3
"""Rank a benchmark's CarpetFuzz option combinations by dry-run coverage.

CarpetFuzz's rank_combination.py at trial start, on this trial's binary: each
combination gets a value for every option that takes one (from dict.json), is
run once on the first seed with afl-showmap, and the combinations are sorted by
the number of tuples covered. The output is the stub file for afl-fuzz -K: a
count line, then one command per line with @@.

Ranking stops after --time-limit seconds (it is part of the trial's fuzzing
budget); combinations not dry-run by then follow the ranked ones in PICT order.
"""
import argparse
import json
import os
import random
import re
import subprocess
import tempfile
import time


def render(combination, dictionary, rng):
    """Combination ("-a -b ") -> command line, as CarpetFuzz's restoreStub."""
    parts = []
    for opt in combination.split():
        entry = dictionary["options"].get(opt)
        if entry:
            parts.append(f"{opt}{entry['connector']}{rng.choice(entry['values'])}")
        else:
            parts.append(opt)
    return " ".join(dictionary["synopsis"].replace("OPTIONS", " ".join(parts)).split())


def dry_run_coverage(stub, bindir, seed, showmap):
    """Tuples covered by one run of stub on seed (CarpetFuzz's getDryRunCoverage);
    None if afl-showmap gave no result."""
    # The instrumented target reads its argv, NUL-separated, from the file it gets.
    argv = stub.replace("@@", seed).split(" ")
    with tempfile.NamedTemporaryFile("wb", delete=False) as f:
        f.write(b"\0".join(a.encode() for a in argv) + b"\0")
    # afl-showmap refuses targets whose coverage map is larger than its default
    # (ffmpeg needs ~570k entries) unless AFL_MAP_SIZE is set; afl-fuzz sizes it
    # automatically. A larger map than needed does not change the tuple count.
    env = dict(os.environ)
    env.setdefault("AFL_MAP_SIZE", str(1 << 23))
    try:
        out = subprocess.run([showmap, "-e", "-o", "/dev/null", "--",
                              os.path.join(bindir, argv[0]), f.name],
                             capture_output=True, text=True, errors="replace", timeout=30, env=env).stdout
    except subprocess.TimeoutExpired:
        return None
    finally:
        os.unlink(f.name)
    found = re.findall(r"Captured (\d+) tuples", out)
    return int(found[0]) if found else None


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--combinations", required=True)
    parser.add_argument("--dict", required=True)
    parser.add_argument("--bindir", required=True)
    parser.add_argument("--seeddir", required=True)
    parser.add_argument("--showmap", required=True)
    parser.add_argument("--time-limit", type=float, required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    with open(args.combinations) as f:
        combinations = [line for line in f.read().splitlines() if line.strip()]
    with open(args.dict) as f:
        dictionary = json.load(f)
    # CarpetFuzz dry-runs the first seed: it is the most likely to be fuzzed early.
    seed = os.path.join(args.seeddir, sorted(os.listdir(args.seeddir))[0])

    rng = random.Random()
    stubs = [render(c, dictionary, rng) for c in combinations]
    deadline = time.monotonic() + args.time_limit
    coverage = {}
    failed = 0
    for stub in stubs:
        if time.monotonic() >= deadline:
            break
        if stub not in coverage:
            tuples = dry_run_coverage(stub, args.bindir, seed, args.showmap)
            failed += tuples is None
            coverage[stub] = tuples or 0

    ranked = sorted(coverage, key=coverage.get, reverse=True)
    ranked += [s for s in dict.fromkeys(stubs) if s not in coverage]
    with open(args.out, "w") as f:
        f.write(f"{len(ranked)}\n" + "\n".join(ranked) + "\n")
    print(f"[+] carpetfuzz ranking: {len(coverage)}/{len(ranked)} combinations dry-run "
          f"(best {max(coverage.values(), default=0)} tuples, {failed} dry runs failed), "
          f"{len(ranked) - len(coverage)} left unranked at the time limit")


if __name__ == "__main__":
    main()
