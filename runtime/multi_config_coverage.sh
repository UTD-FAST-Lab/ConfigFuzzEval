#!/bin/bash
# Coverage for a trial fuzzed by runtime/multi_config_run.sh. Started by the
# coverage runner image when MULTI_CONFIG=1, with OUT (the trial root),
# RUN_TARGET (from the coverage build's run_target.sh) and FUZZER_NAME.
#
# For every fuzzed configuration (rt_run.jsonl), the inputs that first appeared
# under it are replayed by the fuzzer's own coverage.py with that configuration's
# arguments; the per-configuration profiles are then merged into one
# coverage/report.json and coverage/report.txt at the trial root, where the
# framework reads them.
ROOT=$OUT
BINARY=$(echo $RUN_TARGET | awk '{print $1}')
CORPUS_DIR=$(python3 -c "import json; print(json.load(open('/runtime/supported_fuzzers.json'))['$FUZZER_NAME']['corpus_dir'])")
WORK=/tmp/rt_coverage

python3 /runtime/select_new_inputs.py $ROOT $CORPUS_DIR $WORK | while read i n; do
    echo "[runtime] config $i: $n new inputs to replay"
done

PROFILES=()
for line_no in $(seq 1 $(grep -c . $ROOT/rt_run.jsonl)); do
    i=$(sed -n "${line_no}p" $ROOT/rt_run.jsonl | python3 -c "import json, sys; print(json.load(sys.stdin)['config'])")
    ARGS=$(python3 -c "import json; print(' '.join(json.load(open('$ROOT/rt_configs.json'))['configs'][$i]))")
    [ -z "$(ls $WORK/config_$i/$CORPUS_DIR 2>/dev/null)" ] && continue
    echo "[runtime] coverage for config $i: $ARGS"
    OUT=$WORK/config_$i RUN_TARGET="$BINARY $ARGS" python3 /fuzzer/coverage.py > $WORK/config_$i.log 2>&1
    if [ -f $WORK/config_$i/coverage/merged.profdata ]; then
        mkdir -p $ROOT/config_$i/coverage
        cp $WORK/config_$i/coverage/merged.profdata $ROOT/config_$i/coverage/merged.profdata
        PROFILES+=($ROOT/config_$i/coverage/merged.profdata)
    else
        echo "[runtime] no profile for config $i (see the fuzzer's coverage.py output below)"
        tail -5 $WORK/config_$i.log
    fi
done

mkdir -p $ROOT/coverage
if [ ${#PROFILES[@]} -eq 0 ]; then
    echo "[runtime] no coverage profiles produced"
    exit 0
fi
echo "[runtime] merging ${#PROFILES[@]} configuration profiles"
llvm-profdata merge -sparse -o $ROOT/coverage/merged.profdata "${PROFILES[@]}"
# LCOV, like every fuzzer's coverage.py: read by common/report_generation.py and
# the SuperC analysis (cfg-analysis/).
llvm-cov export $BINARY -instr-profile=$ROOT/coverage/merged.profdata -format=lcov > $ROOT/coverage/report.json
llvm-cov report $BINARY -instr-profile=$ROOT/coverage/merged.profdata > $ROOT/coverage/report.txt
echo "[runtime] coverage report at $ROOT/coverage/report.txt"
