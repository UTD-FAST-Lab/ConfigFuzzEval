#!/bin/bash
# Fuzzes a trial's configurations one after another (any --runtime-strategy except
# default). Started by the runner image when MULTI_CONFIG=1, inside the trial
# container, with:
#   /rt_configs.json   this trial's shuffled configurations (common/rt_config_generator.py)
#   /fuzzer/run.sh     the fuzzer's normal, single-session run.sh
#   OUT, RUNTIME, RUN_TARGET (from run_target.sh), FUZZER_NAME, MIN_CONFIG_TIME
#
# Each configuration gets an equal share of the remaining time (at least
# MIN_CONFIG_TIME seconds, so only the first RUNTIME / MIN_CONFIG_TIME
# configurations run when there are more), and starts from the previous
# configuration's corpus. The fuzzer's run.sh is called with:
#   OUT=$OUT/config_<i>  RUNTIME=<slice>  RUN_TARGET="<binary> <config args>"
#   SEED_DIR=<previous corpus, or /benchmark/seed for the first one>
ROOT=$OUT
MIN_CONFIG_TIME=${MIN_CONFIG_TIME:-60}
BINARY=$(echo $RUN_TARGET | awk '{print $1}')
CORPUS_DIR=$(python3 -c "import json; print(json.load(open('/runtime/supported_fuzzers.json'))['$FUZZER_NAME']['corpus_dir'])")

TOTAL=$(python3 -c "import json; print(len(json.load(open('/rt_configs.json'))['configs']))")
N=$(( RUNTIME / MIN_CONFIG_TIME ))
[ $N -lt 1 ] && N=1
[ $N -gt $TOTAL ] && N=$TOTAL
echo "[runtime] fuzzing $N of $TOTAL configurations for $RUNTIME s"

cp /rt_configs.json $ROOT/rt_configs.json
: > $ROOT/rt_run.jsonl

# Carried-over inputs may crash or time out under the next configuration's options.
export AFL_IGNORE_SEED_PROBLEMS=1

DEADLINE=$(( $(date +%s) + RUNTIME ))
SEED_DIR=/benchmark/seed
LAST=
for (( i = 0; i < N; i++ )); do
    # Split the time left evenly, so time lost to fuzzer start-up does not push
    # the last configurations past RUNTIME.
    LEFT=$(( DEADLINE - $(date +%s) ))
    [ $LEFT -le 0 ] && break
    SLICE=$(( LEFT / (N - i) ))
    [ $SLICE -lt 1 ] && SLICE=1
    ARGS=$(python3 -c "import json; print(' '.join(json.load(open('/rt_configs.json'))['configs'][$i]))")
    python3 -c "import json, sys; print(json.dumps({'config': $i, 'args': json.load(open('/rt_configs.json'))['configs'][$i], 'slice': $SLICE, 'seed_dir': sys.argv[1]}))" \
        "$SEED_DIR" >> $ROOT/rt_run.jsonl
    echo "[runtime] config $i/$N for $SLICE s: $ARGS"

    mkdir -p $ROOT/config_$i
    LAST=$ROOT/config_$i
    # run.sh expands $RUN_TARGET unquoted; bash -f turns off filename expansion so
    # values such as xmllint's "--xpath //*" reach the target as generated.
    OUT=$ROOT/config_$i RUNTIME=$SLICE RUN_TARGET="$BINARY $ARGS" SEED_DIR=$SEED_DIR \
        timeout -s INT $(( SLICE + 30 )) bash -f /fuzzer/run.sh

    if [ -n "$(ls $ROOT/config_$i/$CORPUS_DIR 2>/dev/null)" ]; then
        SEED_DIR=$ROOT/config_$i/$CORPUS_DIR
    fi
done

# Point default/ at the last configuration's output, like a single run.
[ -n "$LAST" ] && [ -d "$LAST/default" ] && ln -sfn ${LAST#$ROOT/}/default $ROOT/default
exit 0
