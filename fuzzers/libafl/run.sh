# Skip seeds that crash or time out instead of aborting the whole trial.
export AFL_IGNORE_SEED_PROBLEMS=1
/fuzzer/fuzzers/forkserver/libafl-fuzz/test/AFLplusplus/afl-fuzz -i ${SEED_DIR:-/benchmark/seed} -o $OUT   -V $RUNTIME $RUN_TARGET 