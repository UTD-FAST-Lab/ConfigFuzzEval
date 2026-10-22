# SuperC presence-condition analysis

[ConfigFuzzEval](../README.md) › [Documentation](README.md) › SuperC

## What it does

[SuperC](https://github.com/appleseedlab/superc) parses C with every configuration at once and gives each source line its *presence condition*: the `#if`/`#ifdef` condition under which it is compiled, such as `defined(HAVE_LIBDEBUGINFOD)` or `!defined(_WIN32) && HAVE_MMAP`. `common/superc.py` joins those conditions with the trials' line coverage, to show which conditional code each fuzzer reached. It runs at the end of every experiment unless `no_superc` (in an [experiment file](run-experiment-file.md)) or `--no-superc` (on the [command line](run-command-line.md)) turns it off; a failure is logged and does not fail the experiment. On a finished experiment:

```bash
python3 common/post_analysis.py --state /path/to/experiment-data/EXP_NAME/experiment_state.pkl --superc
python3 common/superc.py /path/to/experiment-data/EXP_NAME [-o OUT_DIR] [--jobs N] [--timeout SECONDS]   # without a state
```

## How it works

1. **Once per benchmark build** (copy 0 of each compile-time strategy, not once per trial: the conditions depend only on the source), SuperC runs on every `.c` file of the build's coverage report. The sources are those of that coverage build: the experiment's own copy if it has one (`benchmarks/coverage_<copy>/source`), otherwise copied out of the coverage image `fbpp/benchmark:coverage_<copy>` (object files left out), so the lines match the coverage. Files run in parallel on the experiment's cores, each with a time limit (600 s by default) and its own JVM; a file analysed before is not analysed again.
2. **Build flags** come from `benchmarks/<name>/superc_flags.txt`, one per line, as the benchmark's build uses them: `-I <dir>` relative to the benchmark's source root (for example `-I bfd` for `/binutils-2.47/bfd`) and `-D NAME[=VALUE]` (for example `-D HAVE_CONFIG_H`, which most builds pass so that their sources include `config.h`). Every benchmark has one; a new benchmark needs one too (without it only the root is an include directory). A missing `-D` shows up as an `#error` in the file's SuperC log (ffmpeg's `libavutil/common.h` needs `-D __STDC_CONSTANT_MACROS`, as SuperC also explores `defined(__cplusplus)`). SuperC runs with `-nostdinc`, so system headers such as `stdio.h` are not read (by design: only the program's own conditions are wanted); the "header not found" lines for them in the logs are expected, also for replacement headers with system names that a build does not use (gnulib's `lib/stdio.h`, ffmpeg's `compat/`, x264's `extras/`).
3. **For every trial**, each condition gets the lines the coverage build instrumented under it and those the trial covered. Lines are keyed by their full path in the build, so files with the same name in different folders stay apart. Trials under runtime strategies are included, and the copies of a [compile-time strategy](../README.md#compile-time-strategies) are combined.
4. **Per benchmark**, the arms (`fuzzer[strategy]`, as in the [statistics report](statistics-report.md)) are compared by the conditions their trials covered together.

Conditions `1` (always compiled) and `0` (compiled in no configuration, such as `#if 0`) are left out of the counts. A condition is *in the build* when the coverage build instrumented at least one of its lines (code under `defined(_WIN32)`, say, is not), and *covered* when a trial executed one.

## Outputs

| File | Contents |
|---|---|
| `<report_filestore>/EXP_NAME/superc/index.html` | per benchmark and arm, with the arm's trials combined both ways: conditions in the build; covered by the union of the trials, by the mean trial (± standard deviation), by every trial and by the median trial; conditional lines covered (union and mean); and the conditions only one arm covered |
| `.../superc/pc_summary.csv` | the same as a table (`*_union`, `*_mean`, `*_sd`, `conditions_covered_every_trial`, `conditions_covered_median_trial`) |
| `.../superc/<benchmark>_pc_comparison.csv` | every condition with its instrumented lines, the arms that covered it, and per arm its covered lines in the union (`covered_lines:<arm>`), its mean covered lines over the trials (`mean_covered_lines:<arm>`) and the number of trials that covered it (`trials_covered:<arm>`) |
| `.../superc/cross_strategy.csv` | for a benchmark run under several compile-time strategies: per arm (and `all fuzzers`) and strategy, the conditions in the build and covered, covered only under that strategy, missed (and of those, not compiled), gained and lost against default |
| `.../superc/<benchmark>_strategy_comparison.csv` | per arm, every condition with its covered and instrumented lines under each strategy (`-` when no build of the strategy compiled it) |
| `<experiment>/data/<trial>/pc_analysis/pc_coverage_summary.{json,csv}` | every condition of one trial |
| `<experiment>/superc/<copy>/` | SuperC's trees (`pc/<path>.json`), logs (`logs/<path>.log`), `status.tsv` (file, exit code (124: timed out), seconds), and the files and includes it ran with |

## Limits

- **Code in headers has no condition.** SuperC reports conditions for the lines of the `.c` file it parses, so header code (for example bfd's `coffcode.h`, included by many `.c` files) is not attributed. The report gives these lines, and any other covered lines without a condition, next to the counts.
- **SuperC's top region ends anywhere.** It often ends at line 1, or before blocks it does report, so the analysis takes it to cover the whole file: every line outside the reported `#if` blocks is top-level code. Only when a conditional directive (outside comments) is in no reported block did SuperC really stop early; the lines from that directive on then have no condition, and the experiment log names the file. On the 12 benchmarks this happens for no file.
- **SuperC fails on a few files**: 2 of the 2,795 `.c` files of the 12 benchmarks' builds (libpng `pngsimd.c`, a NullPointerException in SuperC; ffmpeg `libavcodec/ccaption_dec.c`, a lexer error). They have exit code 1 in `status.tsv` and no conditions.
- **A line on the boundary of two blocks** (an `#elif` or `#else` line) belongs to both, as SuperC reports it.
- **Only `.c` files** of the coverage report are analysed; the conditions are those of copy 0 of each compile-time strategy.

## Docker image

The image is `fbpp/superc_runner:<hash of cfg-analysis/>` (SuperC at a fixed commit), so a change to `cfg-analysis/` builds a new one. It runs as the calling user, so its output can be removed and redone without root.

## See also

- [Presence conditions tab](web-app.md#presence-conditions) of the web app, which shows these results.
- [Coverage reports](coverage-reports.md): the line coverage the analysis is joined with.
- [Compile-time strategies](README.md#compile-time-strategies-in-depth): how the benchmark builds it compares are made.
