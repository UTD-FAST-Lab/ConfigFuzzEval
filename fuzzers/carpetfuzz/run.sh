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
# Without a time limit (RUNTIME 0 or unset: continuous mode), ranking gets
# CARPETFUZZ_RANK_TIME seconds (default 600) and fuzzing has no limit.
START=$(date +%s)
if [ "${RUNTIME:-0}" -gt 0 ] 2>/dev/null; then RANK_TIME=$((RUNTIME / 10)); else RANK_TIME=${CARPETFUZZ_RANK_TIME:-600}; fi
python3 /fuzzer/rank.py --combinations $CF/combinations.txt --dict $CF/dict.json \
    --bindir /benchmark --seeddir /benchmark/seed --showmap /fuzzer/afl-showmap \
    --time-limit $RANK_TIME --out $OUT/ranked_stubs.txt || exit 1
LIMIT=""
if [ "${RUNTIME:-0}" -gt 0 ] 2>/dev/null; then LIMIT="-V $((RUNTIME - ($(date +%s) - START)))"; fi

/fuzzer/afl-fuzz -i /benchmark/seed -o $OUT -K $OUT/ranked_stubs.txt $LIMIT -- $RUN_TARGET
