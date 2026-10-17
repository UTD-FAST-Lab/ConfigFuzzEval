# A time limit when RUNTIME > 0 (evaluation mode); none when it is 0 or unset (continuous mode).
LIMIT=""; [ "${RUNTIME:-0}" -gt 0 ] 2>/dev/null && LIMIT="-V $RUNTIME"
# Skip seeds that crash or time out instead of aborting the whole trial.
export AFL_IGNORE_SEED_PROBLEMS=1
/fuzzer/fuzzers/forkserver/libafl-fuzz/test/AFLplusplus/afl-fuzz -i ${SEED_DIR:-/benchmark/seed} -o $OUT   $LIMIT $RUN_TARGET 