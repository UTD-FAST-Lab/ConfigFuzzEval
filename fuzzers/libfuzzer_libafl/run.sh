cd /benchmark
nohup /benchmark/libfuzzerrunner  -i /benchmark/corpus -o $OUT  > log1.log 2>&1 &
timeout --signal=SIGINT $RUNTIME env LLVM_PROFILE_FILE=$OUT/profraw/default.profraw /benchmark/libfuzzerrunner  -i /benchmark/corpus -o $OUT