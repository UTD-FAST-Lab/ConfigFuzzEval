CONFIGS_FILE="/benchmark/ranked_stubs.txt"
PREV_INPUT="/benchmark/seed"

# Read number of configs from first line
NUM_CONFIGS=$(head -n 1 "$CONFIGS_FILE")

if [ "$NUM_CONFIGS" -eq 0 ]; then
    echo "Error: NUM_CONFIGS in $CONFIGS_FILE is 0"
    exit 1
fi

# Compute timeout for each config
TIMEOUT=$(( RUNTIME / NUM_CONFIGS ))

echo "RUNTIME=$RUNTIME, NUM_CONFIGS=$NUM_CONFIGS, TIMEOUT=$TIMEOUT"

# Skip first line (header) when looping through configs
i=0
tail -n +2 "$CONFIGS_FILE" | while IFS= read -r config; do
    OUTPUT_DIR="$OUT/run_$i"
    mkdir -p "$OUTPUT_DIR"

    # Insert configs before the @@ inside RUN_TARGET
    CMD=$(echo "$RUN_TARGET" | sed "s/@@/$config @@/")

     /fuzzer/fuzzers/forkserver/libafl-fuzz/test/AFLplusplus/afl-fuzz \
        -i "$PREV_INPUT" \
        -o "$OUTPUT_DIR" \
        -V $TIMEOUT \
        $CMD

    PREV_INPUT="$OUTPUT_DIR/default/queue"
    i=$((i+1))
done
