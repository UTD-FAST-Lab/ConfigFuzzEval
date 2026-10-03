#!/bin/bash
# ProphetFuzz fuzzes with LLM-predicted option combinations, passed with -K in the
# same format as ranked_stubs.txt (a count line, then one command per line with @@).
# Use the benchmark's prophet_argvs.txt if it provides one, else ranked_stubs.txt.
ARGVS=/benchmark/ranked_stubs.txt
if [ -f /benchmark/prophet_argvs.txt ]; then
    ARGVS=/benchmark/prophet_argvs.txt
fi

# Same settings as ProphetFuzz's fuzzing_handler/run_fuzzing.sh.
export AFL_IGNORE_SEED_PROBLEMS=1
/fuzzer/afl-fuzz -i /benchmark/seed -o $OUT -m none -K $ARGVS -V $RUNTIME -- $RUN_TARGET
