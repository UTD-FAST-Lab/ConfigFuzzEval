#!/usr/bin/env python3
"""For runtime/multi_config_coverage.sh: copies, for every fuzzed configuration,
only the corpus inputs that first appeared under it (by content) into a separate
output folder laid out like the fuzzer's own, so the fuzzer's coverage.py replays
each input once, under the configuration that found it. Inputs carried over from
earlier configurations are not replayed again under every later one.

Usage: select_new_inputs.py <trial root> <corpus_dir> <dest root>
Writes <dest root>/config_<i>/<corpus_dir>/... and prints "<i> <new inputs>" per config.
"""

import hashlib
import json
import os
import shutil
import sys


def main():
    root, corpus_dir, dest = sys.argv[1], sys.argv[2], sys.argv[3]
    with open(os.path.join(root, "rt_run.jsonl")) as f:
        fuzzed = [json.loads(line)["config"] for line in f if line.strip()]
    seen = set()
    for i in fuzzed:
        src = os.path.join(root, f"config_{i}", corpus_dir)
        out = os.path.join(dest, f"config_{i}", corpus_dir)
        os.makedirs(out, exist_ok=True)
        new = 0
        if os.path.isdir(src):
            for name in sorted(os.listdir(src)):
                path = os.path.join(src, name)
                if not os.path.isfile(path):
                    continue
                with open(path, "rb") as f:
                    digest = hashlib.sha1(f.read()).hexdigest()
                if digest in seen:
                    continue
                seen.add(digest)
                shutil.copy(path, os.path.join(out, name))
                new += 1
        print(i, new)


if __name__ == "__main__":
    main()
