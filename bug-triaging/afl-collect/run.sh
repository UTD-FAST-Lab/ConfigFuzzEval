#!/bin/bash
set -e

echo "TEST_TRIAGE is set to: $TEST_TRIAGE"

if [ "$TEST_TRIAGE" = "1" ]; then
    echo "Running afl-collect help (triage mode)..."
    exec afl-collect --help
else
    echo "Running afl-collect with target..."
    RUN_TARGET=$(cat /benchmark/run_target.sh)
    export RUN_TARGET
    exec afl-collect -d /triaging_output/crashes.db -e gdb_script -r -rr /fuzzer_output/default/crashes/ /triaging_output/collection_dir \
        -j 8 -- $RUN_TARGET
fi
