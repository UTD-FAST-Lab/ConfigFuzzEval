# VAFuzz drives the target's command-line options through a z3 solver script
# generated from the benchmark's runtime grammar.
SOLVER_DIR=/tmp/vafuzz-solver
mkdir -p $SOLVER_DIR
cp /fuzzer/py-src/generator_helpers.py $SOLVER_DIR/
export PYTHONPATH=/fuzzer/pydeps
python3 /fuzzer/py-src/z3-solver-generator.py /benchmark/rt_grammar.json $SOLVER_DIR/target_z3.py
# Running the solver once creates the presence-condition queue (/tmp/pqeue.pkl).
(cd $SOLVER_DIR && python3 target_z3.py)
/fuzzer/afl-fuzz -i /benchmark/seed -o $OUT -K $SOLVER_DIR/target_z3.py -r /benchmark/rt_grammar.json -w /tmp/pqeue.pkl -q 5000 -V $RUNTIME $RUN_TARGET
