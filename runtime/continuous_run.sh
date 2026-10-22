#!/bin/bash
# One configuration of a continuous-mode runtime-strategy instance (common/continuous.py).
# The campaign starts this in the runner image at every round boundary with:
#   CONFIG_INDEX   n: fuzz configs[n] of $OUT/rt_configs.json into $OUT/config_<n>
#   PREVIOUS       the previous configuration's index (its corpus seeds this one), or empty
#   FUZZER_NAME    for its corpus folder (runtime/supported_fuzzers.json)
# and no time limit (RUNTIME=0): the campaign stops the container at the next round.
ROOT=$OUT
BINARY=$(awk '{print $1}' /benchmark/run_target.sh)
ARGS=$(python3 -c "import json; print(' '.join(json.load(open('$ROOT/rt_configs.json'))['configs'][$CONFIG_INDEX]))")
CORPUS_DIR=$(python3 -c "import json; print(json.load(open('/runtime/supported_fuzzers.json'))['$FUZZER_NAME']['corpus_dir'])")

SEED_DIR=/benchmark/seed
if [ -n "$PREVIOUS" ] && [ -n "$(ls $ROOT/config_$PREVIOUS/$CORPUS_DIR 2>/dev/null)" ]; then
    SEED_DIR=$ROOT/config_$PREVIOUS/$CORPUS_DIR
fi
echo "[continuous] config $CONFIG_INDEX: $ARGS (seeds: $SEED_DIR)"

# Carried-over inputs may crash or time out under this configuration's options.
export AFL_IGNORE_SEED_PROBLEMS=1
mkdir -p $ROOT/config_$CONFIG_INDEX
# run.sh expands $RUN_TARGET unquoted; bash -f turns off filename expansion (see multi_config_run.sh).
OUT=$ROOT/config_$CONFIG_INDEX RUNTIME=0 RUN_TARGET="$BINARY $ARGS" SEED_DIR=$SEED_DIR exec bash -f /fuzzer/run.sh
