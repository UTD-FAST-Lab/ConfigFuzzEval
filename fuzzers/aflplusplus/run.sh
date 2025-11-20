#!/bin/bash
set -euo pipefail

CONFIGS_FILE="/benchmark/ranked_stubs.txt"
PREV_INPUT="/benchmark/seed"

# Read number of configs from first line
NUM_CONFIGS=$(head -n 1 "$CONFIGS_FILE")

case "$NUM_CONFIGS" in
    ''|*[!0-9]*)
        echo "Error: First line of $CONFIGS_FILE must be an integer (got: '$NUM_CONFIGS')"
        exit 1
        ;;
    0)
        echo "Error: NUM_CONFIGS in $CONFIGS_FILE is 0, nothing to run"
        exit 1
        ;;
esac

# Compute timeout for each config
TIMEOUT=$(( RUNTIME / NUM_CONFIGS ))

echo "RUNTIME=$RUNTIME, NUM_CONFIGS=$NUM_CONFIGS, TIMEOUT=$TIMEOUT"

# Skip first line (header) when looping through configs
i=0
tail -n +2 "$CONFIGS_FILE" | while IFS= read -r config; do
    OUTPUT_DIR="$OUT/run_$i"
    mkdir -p "$OUTPUT_DIR"

    # Build final target command (insert config before @@)
    CMD="${RUN_TARGET/@@/$config @@}"

    echo "[$i] Running: $CMD (timeout $TIMEOUT sec)"

        /fuzzer/afl-fuzz \
        -i "$PREV_INPUT" \
        -o "$OUTPUT_DIR" \
        -V "$TIMEOUT" \
        $CMD

    PREV_INPUT="$OUTPUT_DIR/default/queue"
    i=$((i+1))
done
