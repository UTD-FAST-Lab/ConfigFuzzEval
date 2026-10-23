# Running from the command line

[ConfigFuzzEval](../README.md) › [Documentation](README.md) › Command line

Command-line flags are one of the three ways to run an experiment, next to an [experiment file](run-experiment-file.md) and the [web app](web-app.md). With flags, every fuzzer runs on every benchmark with every listed strategy, all with the `trials` and `max_total_time` from `config.yaml`. Like every way, it puts the experiment in the [job queue](README.md#job-queue). Create `config.yaml` first (see [Installation](README.md#installation)).

## The command

Run from the root of the project:

```bash
python3 common/run_experiment.py \
  --config config.yaml \
  --experiment-name EXP_NAME \
  --fuzzers FUZZER1 FUZZER2 ... \
  --benchmarks BENCHMARK1 BENCHMARK2 ... \
  --compiletime STRATEGY1 STRATEGY2 ... \
  --runtime-strategy STRATEGY1 STRATEGY2 ... \
  --bug-triaging TRIAGER1 ... \
  --no-superc
```

The command checks everything, queues the experiment and returns; the experiment runs in the background and its output goes to `experiments/logs/EXP_NAME.log` (see [Job queue](README.md#job-queue)).

Flags:

- `--config`: path to the configuration file from step 1.
- `--experiment-name`: name of this run. Results are stored under `<experiment_filestore>/EXP_NAME`. Use a new name for every run; the run stops if a folder with that name already exists. Required, unless an experiment file gives `experiment_name` (the flag wins if both are given).
- `--fuzzers`: list of fuzzers to run. Each name must match a folder name in `fuzzers/` (aflplusplus, carpetfuzz, configfuzz, libafl, prophetfuzz, vafuzz, zigzagfuzz). Required unless `--experiment` is given.
- `--benchmarks`: list of benchmarks to run. Each name must match a folder name in `benchmarks/` (for example `libxml2_xmllint`). Required unless `--experiment` is given.
- `--compiletime`: list of compile-time configuration strategies. Each name must match a folder name in `compiletime/` (default, handselected, mostenabled, mostdisabled, pairwise, smartrandom; see [Compile-time strategies](../README.md#compile-time-strategies)). Optional; if left out, only `default` is used.
- `--runtime-strategy`: list of run-time configuration strategies. Each name must match a folder name in `runtime/` (default, mostenabled, mostdisabled, pairwise, smartrandom, diversity). Optional; if left out, only `default` is used. See [Runtime strategies](../README.md#runtime-strategies). The earlier names `manual`, `maximum`, `minimum`, `randomsmart` (compile time) and `random` (runtime) are still accepted and mean the same strategies.
- `--bug-triaging`: list of crash triage tools to run after fuzzing. Each name must match a folder name in `bug-triaging/` (gdb-exploitable, afl-collect; see [Crash triage](crash-triage.md)). Optional; if left out, no triage is run.
- `--no-superc`: optional. Turns off the SuperC presence-condition analysis that otherwise runs at the end of the experiment (see [SuperC](superc.md)).
- `--experiment FILE` (or `--groups FILE`): optional. Reads what to run from an experiment file instead of `--fuzzers`, `--benchmarks`, `--compiletime` and `--runtime-strategy` (giving any of those with it is an error). See [Experiment file](run-experiment-file.md).
- `--dry-run`: optional. Checks the configuration, the experiment and every name, prints the planned runs, builds, trials and the estimated duration, and exits. Nothing is built, copied, queued or run, so it is safe to use while another experiment is running.
- `--foreground`: optional, rarely needed. Runs the experiment in this process, attached to the terminal, instead of queueing it; the output still goes to `experiments/logs/EXP_NAME.log` too. The queue starts every experiment this way. By hand it does not wait for other experiments, and closing the terminal stops it.

## Full command

Example that runs every fuzzer on every benchmark with every compile-time strategy, crash triage and SuperC analysis:

```bash
python3 common/run_experiment.py \
  --config config.yaml \
  --experiment-name EXP_NAME \
  --fuzzers aflplusplus carpetfuzz configfuzz libafl prophetfuzz vafuzz zigzagfuzz \
  --benchmarks binutils_nm-new binutils_objdump bison_bison expat_xmlwf ffmpeg_ffmpeg file_file libpng_pngimage libtiff_tiff2pdf libxml2_xmllint pcre2_pcre2test x264_x264 xz_xz \
  --compiletime default handselected mostenabled mostdisabled pairwise smartrandom \
  --bug-triaging gdb-exploitable
```

The runtime strategies apply only to the config-agnostic fuzzers, so they go in a command of their own (or a group of
an [experiment file](run-experiment-file.md)), for example every runtime strategy for AFL++ and LibAFL:

```bash
python3 common/run_experiment.py \
  --config config.yaml \
  --experiment-name EXP_NAME \
  --fuzzers aflplusplus libafl \
  --benchmarks xz_xz pcre2_pcre2test \
  --runtime-strategy default mostenabled mostdisabled pairwise smartrandom diversity
```

Asking for a runtime strategy with a config-aware fuzzer stops the experiment with an error, before anything is built.

## See also

- [Experiment file](run-experiment-file.md): when fuzzers should run on different benchmarks, or with different trials or times.
- [Job queue](README.md#job-queue): following, listing and stopping the experiment.
- [Statistics report](statistics-report.md), [SuperC](superc.md), [Crash triage](crash-triage.md): what the experiment writes at its end.
