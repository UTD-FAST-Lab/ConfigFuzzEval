# Coverage reports

[ConfigFuzzEval](../README.md) › [Documentation](README.md) › Coverage reports

Every trial's coverage is measured at the end of its fuzzing, on the benchmark's coverage build, with the fuzzer's own `fuzzers/<fuzzer>/coverage.py` (LLVM source-based coverage: regions, functions, lines and branches). Each trial's report is in `<experiment>/data/<trial>/coverage/`. This page covers the reports that combine an arm's trials, and redoing the coverage of a finished experiment.

## Combined coverage reports

For every arm and benchmark, the [statistics report](statistics-report.md) combines the arm's trials into one source report in two ways, both written every time (`common/coverage_html.py`). The experiment writes them at its end, and `post_analysis.py --stats` writes them again. They are linked from the statistics report ("Combined coverage reports"), from `statistics/html/index.html`, and from the [web app's Results tab](web-app.md#results). `--no-stats-html` skips them.

- **Union:** `statistics/html/<benchmark>/<arm>/index.html`, llvm-cov's HTML source report of the arm's merged trial profiles, as in FuzzBench's coverage reports. It shows what any trial covered. Profiles only merge on one binary, so for arms whose trials ran on several benchmark copies (a compile-time strategy with many configurations), the union is made from the trials' LCOV reports instead. That report has the same layout as the mean report, with the lines, branches and functions any trial covered, per line the trials that covered it and its total execution count, and `union_files.csv`.
- **Mean:** `statistics/html/mean/<benchmark>/<arm>/index.html`, from the trials' LCOV reports. It gives the mean ± standard deviation over the trials of the regions, functions, lines and branches covered, with the worst and best trial. Per file, it gives the mean lines, branches and functions covered, and the lines covered by every trial and by some. Per source line, it shows how many trials covered it (green: all, yellow: some, red: none) and its mean execution count. `mean_files.csv` has the per-file numbers. The union shows what an arm can reach, the mean what a typical trial reaches, and the per-line counts how reliably it is reached.

Only the source files the coverage build uses are copied out of its Docker image, into `statistics/html/src/`. Without Docker, the mean report is still written, without the source text.

## Redoing the coverage of an experiment

`common/rerun_coverage.py` runs the coverage step again on the fuzzer output of a finished experiment, with this repository's current `fuzzers/<fuzzer>/coverage.py` (for example after fixing it). The experiment's own copy of the fuzzer is not changed. Each trial's `coverage/` is renamed to `coverage_previous/` first (an existing `coverage_previous/` is kept), trials run in parallel on the given cores, and the `lcov_results` copies are refreshed at the end:

```bash
mkdir -p experiments/logs
setsid nohup python3 common/rerun_coverage.py \
  --experiment-path /path/to/experiment-data/EXP_NAME \
  --fuzzer vafuzz --cores 54 \
  > experiments/logs/EXP_NAME_coverage_rerun.log 2>&1 < /dev/null &
```

`--match REGEX` limits it to trial folders whose name matches, and `--first-core` chooses the cores (default: the last `--cores` cores). Each trial's coverage output is in its `coverage_rerun.log`.

A new experiment takes `coverage.py` and `run.sh` from the fuzzer's Docker image, so after changing them remove the image (`docker rmi fbpp/fuzzer:<fuzzer>`) to have it rebuilt.

## VAFuzz coverage

VAFuzz runs every input under a batch of command-line option configurations and saves, for each queue entry, the configurations it ran it with (`default/queue_argvs/id:<N>_<k>`, `+cov` on those that found new edges). Its `coverage.py` replays each queue entry once per saved configuration, with the options placed between the program and its own arguments as the fuzzer's target does; entries without saved configurations (the seeds) run without options. `VAFUZZ_COVERAGE_ARGVS=cov` replays only the `+cov` configurations, which gives the same coverage much faster. `VAFUZZ_COVERAGE_TIMEOUT` (seconds, default 30) limits each execution. Set them in the environment of `run_experiment.py` or `rerun_coverage.py`; they are passed on to the coverage container.

## See also

- [Statistics report](statistics-report.md): the rankings and tests on these numbers.
- [SuperC](superc.md): the same line coverage, grouped by `#if` condition.
- [Continuous mode](README.md#continuous-mode): coverage measured in rounds while the fuzzers run.
