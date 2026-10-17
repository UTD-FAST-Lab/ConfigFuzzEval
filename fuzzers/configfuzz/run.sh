#!/bin/bash
# A time limit when RUNTIME > 0 (evaluation mode); none when it is 0 or unset (continuous mode).
LIMIT=""; [ "${RUNTIME:-0}" -gt 0 ] 2>/dev/null && LIMIT="-V $RUNTIME"
# Generate ConfigFuzz's stub from the benchmark's grammar, then fuzz the binary with
# only the input file as argument: the stub decodes the options from the input.
WORK=/tmp/configfuzz
mkdir -p $WORK
python3 /fuzzer/make_stub.py lib /benchmark/rt_grammar.json > $WORK/stub.c
clang -O2 -w -shared -fPIC -o $WORK/stub.so $WORK/stub.c -lm
python3 /fuzzer/make_stub.py seeds /benchmark/rt_grammar.json /benchmark/seed $WORK/seeds

TARGET_BINARY=$(echo $RUN_TARGET | awk '{print $1}')
AFL_PRELOAD=$WORK/stub.so /fuzzer/afl/afl-fuzz -i $WORK/seeds -o $OUT $LIMIT -- $TARGET_BINARY @@
