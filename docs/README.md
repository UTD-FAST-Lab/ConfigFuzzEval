# ConfigFuzzEval documentation

[ConfigFuzzEval](../README.md) › Documentation

This is the user guide: installing ConfigFuzzEval, running experiments and the job queue that runs them, continuous
campaigns, how the configuration strategies work in detail, and the tests. The concepts (experiments, runs, arms and
the two kinds of configuration strategy) are explained in the [main README](../README.md#concepts).

| Page | What it covers |
|---|---|
| **This page** | [Installation](#installation) · [Running an experiment](#running-an-experiment) · [Job queue](#job-queue) · [Continuous mode](#continuous-mode) · [Strategies in depth](#strategies-in-depth) · [Tests](#tests) |
| [Command line](run-command-line.md) | Running an experiment with command-line flags, every flag, and a full example |
| [Experiment file](run-experiment-file.md) | Running an experiment from a YAML file, written by hand or by the interactive setup: groups, keys, which setting wins, checking a file |
| [Web app](web-app.md) | Starting the web app, and every page and tab, with screenshots |
| [Live demo](live-demo.md) | The demo at https://configfuzzeval.vercel.app/: what is in it and how it differs from the web app |
| [Statistics report](statistics-report.md) | The rankings and statistical tests written at the end of every experiment, and their limits |
| [Coverage reports](coverage-reports.md) | The combined union and mean coverage reports, redoing the coverage, VAFuzz coverage |
| [SuperC](superc.md) | The presence-condition analysis: which `#if` code each fuzzer reached |
| [Crash triage](crash-triage.md) | Replaying and deduplicating crashes with gdb-exploitable and afl-collect |
| [Contributing](CONTRIBUTING.md) | Adding a benchmark or a fuzzer (config-agnostic or config-aware) |

## Installation

### Python packages and tools

```bash
python3 -m pip install -r requirements.txt
```

`requirements.txt` lists every Python package the host side imports (the Docker images install their own). Docker and LLVM 18 (`llvm-profdata`, `llvm-cov`) are needed on the host too.

### The configuration file

Create `config.yaml` in the root of the project. Run this from the root of the project: it writes the sample below, with `$(pwd)` filled in, so the result folders are `results/` inside this checkout without any editing. Then change the settings you need (at least `cores_to_use`):

```bash
cat > config.yaml <<EOF
# Number of independent trials to run for each fuzzer/benchmark pair.
trials: 5

# Fuzzing time per trial, in seconds (86400 = 24 hours).
# If a compile-time strategy produces N configurations of a benchmark,
# each configuration is fuzzed for max_total_time / N seconds.
max_total_time: 86400

# Docker build folders for the base and runner images, relative to the project root.
# Leave these as they are.
base_image_path: docker/base-image
runner_image_path: docker/runner-image

# Absolute paths where results are stored. A run named <name> writes to
# <experiment_filestore>/<name> and <report_filestore>/<name>.
# Written with the project folder by the command in docs/README.md; change them to keep results elsewhere.
experiment_filestore: $(pwd)/results/experiment-data
report_filestore: $(pwd)/results/report-data

# Number of CPU cores to use. The last N cores of the machine are used.
# Use at most (number of CPU cores - 1).
cores_to_use: 40

# Optional: use cores_to_use cores starting at this core instead of the last ones,
# e.g. to run next to another experiment. A trial on core c runs on CPUs c-1 and c,
# so it must be at least 1.
# first_core: 1

# true: if there are more trials than cores, queue the extra trials and run them
# as cores free up. false: stop if there are more trials than cores.
allow_serial_execution: true

# Minimum fuzzing time per configuration with a --runtime-strategy, in seconds.
# Optional (default 60). A trial fuzzes at most max_total_time / min_config_time
# of the strategy's configurations.
min_config_time: 60

# Optional (default 16, at most cores_to_use). Docker images built at the same time.
# Too many parallel builds on a slow disk make Docker time out (DeadlineExceeded).
build_parallelism: 16

# Memory per trial, in MB.
experiment_memory: 4096

# Random seed for the smartrandom and pairwise compile-time strategies and the runtime strategies.
# Use null for no seed.
random_seed: 42

# Not used yet; keep it as false.
serialize_multi_conf: false
EOF
```

`config.yaml` is not tracked by git. The written file has absolute paths (for example `/home/you/FuzzBenchPlusPlus/results/experiment-data`); to keep results somewhere else, such as a bigger disk, change the two filestore lines to absolute paths there.

### Host settings

Before the first experiment, run `run_as_sudo.sh` as root. It sets `core_pattern` to `core` and the CPU governor to `performance`. Experiments still run without these settings, but AFL++ warns, and the coverage numbers are noisier (see [Limits of the analyses](statistics-report.md#limits-of-the-analyses)). The [web app](web-app.md)'s Experiments page shows a red check while either is not set.

```bash
sudo ./run_as_sudo.sh
```

The settings are lost on a reboot.

## Running an experiment

There are three ways to say what to run. All of them put the experiment in the same [job queue](#job-queue), where it
runs in the background:

| Way | Command | Best for |
|---|---|---|
| [Command-line flags](run-command-line.md) | `run_experiment.py --fuzzers ... --benchmarks ...` | every fuzzer on every benchmark with every listed strategy, all with the `trials` and `max_total_time` of `config.yaml` |
| [Experiment file](run-experiment-file.md) | `run_experiment.py --experiment FILE`, or `run_experiment.py` with no flags to [write one interactively](run-experiment-file.md#writing-a-file-interactively) | specific fuzzers on specific benchmarks: groups, each with its own strategies, trials and time, and per-benchmark strategies; also scripts and CI/CD pipelines |
| [Web app](web-app.md) | `webapp/app.py` | the same in a browser, with live progress and the results |

Every experiment writes the [statistics report](statistics-report.md) with its
[combined coverage reports](coverage-reports.md#combined-coverage-reports) at its end, then the
[SuperC](superc.md) analysis and [crash triage](crash-triage.md) when they are asked for.

## Job queue

Every experiment, however it is started ([flags](run-command-line.md), an [experiment file](run-experiment-file.md) or the [web app](web-app.md)), goes through one job queue, `common/jobs.py`:

- **One at a time, in the background.** `run_experiment.py` checks the experiment, queues it and returns. The queue runs jobs (experiments and the web app's post-analyses) one at a time, each as its own detached session (as `setsid nohup` would), so it keeps running when the terminal or the web app is closed. A background worker (`python3 common/jobs.py worker`, started automatically when something is queued) starts the next job when the machine is free and exits when the queue is empty; the web app ticks the same queue while it runs. A job also waits for an experiment run by hand with `--foreground`.
- **A log for every experiment:** `experiments/logs/<name>.log` (created when needed), with the full output, including the build output and errors. The web app's post-analysis jobs log to `experiments/logs/<name>_post_<time>.log`, and the queue worker to `experiments/logs/queue_worker.log`.
- **An experiment file for every experiment:** `experiments/<name>.yaml` (not tracked by git), the experiment as it runs, plus a `record` that `run_experiment.py` writes and that is ignored when the file is read:

  ```yaml
  record:
    queued: "2026-10-16 10:02:11 CDT"
    started: "2026-10-16 10:02:13 CDT"
    estimated_end: "2026-10-19 02:40:00 CDT"  # approximate: assumes everything in the run still needs to be built now (...)
    stop_command: "python3 common/jobs.py stop <name>"  # stops it, queued or running (it runs in the background)
    log: "experiments/logs/<name>.log"
  ```

  `queued` and `stop_command` are written when it is queued, `started` and `estimated_end` when it starts. A copy is kept in the experiment folder as `experiment.yaml`. The file runs again with `--experiment` (with a new `experiment_name`; see [Experiment files](run-experiment-file.md)).
- **The estimated end** adds the build time of every image (base and runner images, fuzzers, benchmark copies and coverage builds, `build_parallelism` at a time, from fixed per-build times in `experiment_plan.estimate_seconds`), the trials packed onto `cores_to_use` cores with a few minutes of coverage replay each, and a few minutes at the end. Images that already exist are not rebuilt, so experiments usually end earlier. `--dry-run` prints the same estimate.

Commands:

```bash
python3 common/jobs.py list                # the queue and recent jobs, with their logs
python3 common/jobs.py stop EXP_NAME       # cancel a queued experiment, or stop a running one
tail -f experiments/logs/EXP_NAME.log          # follow an experiment
```

Stopping kills the experiment's processes and every trial container labelled `fbpp.experiment=<name>`; finished trials are kept (the same as **Stop experiment** in the [web app](web-app.md#header)). `jobs.py` reads the result folders from `config.yaml`; give `--config FILE` before the command for another one.

## Continuous mode

The default **evaluation** mode fuzzes every trial for `max_total_time`, then measures its coverage. **Continuous** mode is for long campaigns:
- every trial fuzzes without a time limit;
- every `interval` seconds, the inputs the fuzzers found since the last round are replayed on the coverage builds;
- the [statistics report](statistics-report.md), [SuperC](superc.md) and [crash triage](crash-triage.md) are then redone, so the web app is always current.

Set it in the [experiment file](run-experiment-file.md) (`common/continuous.py` runs it):

```yaml
experiment_name: pcre2_campaign
mode: continuous
continuous:
  interval: 3600          # seconds between coverage rounds (default 3600, at least 60)
  coverage_cores: 2       # cores kept for the coverage rounds and the analyses (default 1)
  duration: 604800        # optional: stop after this many seconds (default: run until stopped)
groups:
  - fuzzers: [aflplusplus]
    benchmarks: [pcre2_pcre2test]
    runtime_strategy: [default, smartrandom]
    trials: 3             # trials are parallel instances; groups cannot set max_total_time
```

The [web app](web-app.md#new-experiment)'s New experiment form has the same choice (Mode: continuous).

- **Cores:** every trial of every benchmark build is an **instance**: one fuzzing container pinned to its own core.
  - A compile-time strategy with N builds gives N instances per trial.
  - The experiment needs one core per instance plus `coverage_cores`, out of `cores_to_use`. Otherwise it stops before building anything, and the dry run says how many cores it needs.
  - Coverage rounds and the analyses run only on the coverage cores, so they never slow the fuzzers.
- **Each round:** for each instance, `runtime/continuous_coverage.py` copies the queue entries found since the last round into a scratch folder, and runs the fuzzer's own `coverage.py` on it. It then merges the result into the instance's cumulative profile, and rewrites the trial's `coverage/report.json` and `report.txt`.
  - An input is taken once it's at least 30 s old.
  - The cumulative result equals replaying the whole queue at once (checked on aflplusplus/pcre2: identical totals and covered lines and branches).
  - Each round, `<experiment>/continuous/timeline.jsonl` gets every trial's coverage after that round.
- **[Runtime strategies](../README.md#runtime-strategies):** an instance fuzzes one configuration per round. At each round it moves to the next configuration (cycling through them), starting from the previous configuration's corpus, in `config_<n>/`. `rt_run.jsonl` and the trial's `rt_configs.json` record them, as in evaluation mode, so triage and the statistics read them the same way.
- **Fuzzers:** each `run.sh` treats `RUNTIME=0` as no limit. The repository's `run.sh` is mounted over the copy in the fuzzer image, so older images work without a rebuild. AFL++'s own CPU binding is turned off (`AFL_NO_AFFINITY=1`), since Docker already pins each container.
- **Stopping:**
  - **Stop campaign** on the experiment's page, `python3 common/continuous.py stop <experiment folder>`, or the end of `duration`: the fuzzers are stopped, then a last round takes every remaining input and redoes the analyses.
  - **Run a coverage round now** (or `continuous.py round <experiment folder>`): runs a round without waiting for the interval.
  - `python3 common/jobs.py stop NAME` or **Cancel** on the page: kills the campaign at once, without a last round.
  - `continuous.py status <experiment folder>` prints the current round, the next round's time and each instance.
- **In the web app:**
  - A **campaign card** on the experiment's page: the rounds so far, the time to the next round, the instances still fuzzing, and the cores in use.
  - A **Coverage over time** tab: per benchmark, each arm's median trial after every round, with its worst-to-best range shaded.
  - The **statistics report** gets a "Coverage over time" section with the same charts. Its rankings and tests use the latest round.
- **Limits:**
  - A campaign blocks the job queue until it ends, like any experiment.
  - An instance whose fuzzer exits is reported, and isn't restarted. Its inputs so far still count.
  - Crash triage redoes every crash each round (see [Crash triage](crash-triage.md)), so a round takes longer as crashes accumulate.

## Strategies in depth

The [main README](../README.md#concepts) says what the two kinds of configuration strategy are and lists them. This
section explains how each kind runs, its grammar file, how its results are named, and how to add a strategy.

### Compile-time strategies in depth

A compile-time strategy chooses `./configure` options for a benchmark, so each configuration is a different
program to fuzz. It applies to every fuzzer.

How a run works:

1. Before anything is built, `common/ct_strategy_applicator.py` runs `compiletime/<strategy>/strategy.py` for each
   benchmark that uses it. The strategy reads the benchmark's `ct_grammar.json` and returns a list of option strings,
   one per configuration (for example `--disable-debug --enable-encoders=lzma1,lzma2`). `smartrandom` and `pairwise`
   use `random_seed` from `config.yaml`, so runs are reproducible; the other strategies are deterministic.
2. For each configuration, the benchmark folder is copied to `benchmarks/cts_<strategy>_<benchmark>_<i>`, and the
   options replace the `{{CT_CONFIGURATION}}` placeholder on the `./configure` line of the copy's `build.sh`. Each
   copy is built once for each fuzzer that runs on it, and once as a coverage build.
3. Every trial runs on every copy, with its time split between them: with N configurations, each copy is fuzzed
   for `max_total_time / N` seconds. In the reports, a trial's coverage is the union of its copies, so a strategy
   with many configurations is compared with the same total fuzzing time as `default`.

The grammar, `benchmarks/<name>/ct_grammar.json`, lists the benchmark's `./configure` options:

- `options`: each with a `name`, a `type` (`bool`, or `choice` with its `choices`), a `default`, and `cli`: `enable`
  for `--enable-<name>`/`--disable-<name>`, or `with` for `--with-<name>`/`--without-<name>`. A choice is passed as
  `--<cli>-<name>=<value>`.
- `constraints`: rules between options, such as `{"opt": "relaxng", "val": true, "then": [{"opt": "schemas", "val": true}]}`
  (RelaxNG needs schemas). Every strategy except `handselected` only returns configurations that satisfy them.
- `removed`: options the strategies never touch, each with its `reason`, for example because `build.sh` already sets
  them.

Every compile-time strategy needs the benchmark's `ct_grammar.json`, also `default`, and the benchmark's `build.sh`
needs the placeholder. The copies are temporary: the experiment removes them when it ends.

### Runtime strategies in depth

A runtime strategy chooses command-line options for the benchmark's program, so one build is fuzzed under several
configurations. It applies to the config-agnostic fuzzers, those in `runtime/supported_fuzzers.json` (aflplusplus,
libafl; see [Registering a fuzzer](CONTRIBUTING.md#registering-it)).

How a run works:

1. Before trials start, `common/rt_config_generator.py` runs `runtime/<strategy>/strategy.py`
   for every strategy, benchmark and trial, and writes the shuffled configurations to
   `<experiment>/rt_configs/<strategy>/<benchmark>/trial_<k>.json`. The order depends on
   `random_seed`, the strategy, the benchmark and the trial, so trials differ, runs are
   reproducible, and all supported fuzzers get the same configurations.
2. The trial container gets that file and `MULTI_CONFIG=1`, and runs
   `runtime/multi_config_run.sh`: the configurations are fuzzed one after another, each for an
   equal share of the trial's time (at least `min_config_time` seconds, 60 by default; under a
   compile-time strategy, the share of the trial's time for its copy), each starting from the
   previous configuration's corpus. The fuzzer's own `run.sh` is called once per configuration.
3. `runtime/multi_config_coverage.sh` replays each input under the configuration that found it,
   using the fuzzer's own `coverage.py`, and merges everything into one report per trial.

The grammar, `benchmarks/<name>/rt_grammar.json`, lists the program's command-line options:

- `cmdline`: the command, with `$inopts` where the options go and `$INPUTFILE` for the input, for example
  `$inopts -c $INPUTFILE` for xz.
- `options`: each with its `opt` (such as `-z`) and `type`; `connector` joins an option and its value.
- `depend` and `conflict`: options that need, or exclude, other options. `maxcombs` and `strmax` limit the
  combinations and string values a strategy generates.
- `exit_options`: options the strategies never use: with them the target exits without processing its input (help, version, listings, or a schema/DTD file that does not exist), so every configuration containing one would fuzz nothing.

### Configurations per strategy

How many configurations each strategy makes, with `random_seed: 42` (`config.yaml`'s default):

- **Compile time:** `default`, `handselected`, `mostenabled` and `mostdisabled` make 1 build each, and `smartrandom`
  makes 10, on every benchmark. `pairwise` depends on the grammar (below).
- **Runtime:** `mostenabled` and `mostdisabled` make 1 configuration each, and `smartrandom` and `diversity` make 50,
  on every benchmark. `pairwise` depends on the grammar (below; for trial 0, as each trial's seed differs slightly).

| Benchmark | Pairwise (compile time) | Pairwise (runtime) |
|---|---|---|
| binutils_nm-new | 16 | 216 |
| binutils_objdump | 16 | 1,013 |
| bison_bison | 20 | 240 |
| expat_xmlwf | 11 | 139 |
| ffmpeg_ffmpeg | 12 | 351 |
| file_file | 9 | 211 |
| libpng_pngimage | 10 | 13 |
| libtiff_tiff2pdf | 30 | 186 |
| libxml2_xmllint | 22 | 138 |
| pcre2_pcre2test | 45 | 245 |
| x264_x264 | 14 | 647 |
| xz_xz | 19 | 114 |

A trial fuzzes at most `max_total_time / min_config_time` of a runtime strategy's configurations (1,440 in 24 hours
with the default 60 seconds), so with 24-hour trials every configuration above runs; with 50 configurations, each
gets about 29 minutes. Under a compile-time strategy with N builds, the same applies to each build's
`max_total_time / N` seconds.

### Result names

Every trial has its own folder in `<experiment_filestore>/<experiment>/data/`, named after its run:

| Run | Trial folder | Arm in the reports |
|---|---|---|
| default strategies | `<fuzzer>_cts_default_<benchmark>_0_trial_<k>` | `<fuzzer>` |
| compile-time strategy | `<fuzzer>_cts_<strategy>_<benchmark>_<i>_trial_<k>`, one per configuration `<i>` | `<fuzzer>{cts:<strategy>}` |
| runtime strategy | `<fuzzer>_rts_<strategy>_cts_default_<benchmark>_0_trial_<k>` | `<fuzzer>[<strategy>]` |

Both kinds can be combined in one run: a runtime strategy then runs on every compile-time configuration, as
`<fuzzer>_rts_<strategy>_cts_<strategy>_<benchmark>_<i>_trial_<k>`, reported as `<fuzzer>[<strategy>]{cts:<strategy>}`.

### Adding a strategy

- **Compile-time:** add `compiletime/<name>/strategy.py` with a `request_configurations(grammar_file, random_seed=None)`
  function that returns a list of `./configure` option strings, one per configuration (`[""]` is one build with no
  extra options). The name is then accepted everywhere, with no other change.
- **Runtime:** add `runtime/<name>/strategy.py` with a `request_configurations(grammar, rng)`
  function that returns a list of argument lists (see `runtime/rt_common.py`). To support another fuzzer, add it to
  `runtime/supported_fuzzers.json` with the folder its corpus is written to, and make its `run.sh` read seeds from
  `${SEED_DIR:-/benchmark/seed}`.

Benchmarks and fuzzers are added as described in [Contributing](CONTRIBUTING.md). The web app's
[Documentation page](web-app.md#documentation-page) describes these and the other plugin interfaces.

## Tests

```bash
python3 -m pytest tests
```
