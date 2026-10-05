# VAFuzz drives the target's command-line options through a z3 solver script
# generated from the benchmark's runtime grammar.
SOLVER_DIR=/tmp/vafuzz-solver
mkdir -p $SOLVER_DIR
cp /fuzzer/py-src/generator_helpers.py $SOLVER_DIR/
export PYTHONPATH=/fuzzer/pydeps
python3 /fuzzer/py-src/z3-solver-generator.py /benchmark/rt_grammar.json $SOLVER_DIR/target_z3.py
# Running the solver once creates the presence-condition queue (/tmp/pqeue.pkl).
(cd $SOLVER_DIR && python3 target_z3.py)
# The argv-instrumented target reads its options from the file in argv[1];
# afl-fuzz writes them to config.seed next to the target binary. Use a private
# copy of the target so trials sharing /benchmark don't share config.seed.
TARGET_DIR=/tmp/vafuzz-target
mkdir -p $TARGET_DIR
read -r BINARY ARGS <<< "$RUN_TARGET"
cp "$BINARY" $TARGET_DIR/
TARGET="$TARGET_DIR/$(basename $BINARY) $TARGET_DIR/config.seed $ARGS"
# -q: executions per option config. -u 0.33: when switching configs, use z3
# generator 3 or 1 a third of the time each (argv havoc otherwise). -j 0.1:
# pick a random queued presence condition 10% of the time.
/fuzzer/afl-fuzz -i /benchmark/seed -o $OUT -K $SOLVER_DIR/target_z3.py -r /benchmark/rt_grammar.json -w /tmp/pqeue.pkl -q 5000 -u 0.33 -j 0.1 -V $RUNTIME $TARGET
