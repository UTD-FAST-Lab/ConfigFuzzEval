#!/bin/bash
# CarpetFuzz: fuzz the option combinations that CarpetFuzz derived from the
# target's man page (benchmarks/<name>/carpetfuzz/, made offline by
# fuzzers/carpetfuzz/analysis/generate.sh), ranked by dry-run coverage on this
# trial's binary.
CF=/benchmark/carpetfuzz
if [ ! -f $CF/combinations.txt ] || [ ! -f $CF/dict.json ]; then
    echo "carpetfuzz: $CF/combinations.txt or dict.json is missing; run fuzzers/carpetfuzz/analysis/generate.sh" >&2
    exit 1
fi

# Ranking is part of the trial: it gets at most a tenth of the budget, and
# fuzzing gets what is left.
START=$(date +%s)
python3 /fuzzer/rank.py --combinations $CF/combinations.txt --dict $CF/dict.json \
    --bindir /benchmark --seeddir /benchmark/seed --showmap /fuzzer/afl-showmap \
    --time-limit $((RUNTIME / 10)) --out $OUT/ranked_stubs.txt || exit 1
REMAINING=$((RUNTIME - ($(date +%s) - START)))

/fuzzer/afl-fuzz -i /benchmark/seed -o $OUT -K $OUT/ranked_stubs.txt -V $REMAINING -- $RUN_TARGET
