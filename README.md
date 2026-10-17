# FuzzBenchPlusPlus

## Build instructions

### 0. Install the Python packages

```bash
python3 -m pip install -r requirements.txt
```

`requirements.txt` lists every Python package the host side imports (the Docker images install their own). Docker and LLVM 18 (`llvm-profdata`, `llvm-cov`) are needed on the host too.

### 1. Create the configuration file

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
# Written with the project folder by the command in README.md; change them to keep results elsewhere.
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

# Random seed for the randomsmart compile-time strategy (other strategies ignore it).
# Use null for no seed.
random_seed: 42

# Not used yet; keep it as false.
serialize_multi_conf: false
EOF
```

`config.yaml` is not tracked by git. The written file has absolute paths (for example `/home/you/FuzzBenchPlusPlus/results/experiment-data`); to keep results somewhere else, such as a bigger disk, change the two filestore lines to absolute paths there.

### 2. Run an experiment

There are four ways to say what to run. All of them put the experiment in the same job queue, where it runs in the background (see "How experiments run" below):

- **Interactive setup** (no flags, see "Interactive setup" below): asks what to run in the terminal, saves it as an experiment file and queues it.
- **Web app** (see "Web app" below): the same in a browser, with live progress.
- **Command-line flags** (below): every fuzzer runs on every benchmark with every listed strategy, all with the `trials` and `max_total_time` from `config.yaml`.
- **An experiment file** (`--experiment` or `--groups`, see "Experiment files" below): groups of fuzzers and benchmarks, so specific fuzzers run on specific benchmarks, each group with its own strategies and optionally its own `trials` and `max_total_time`, plus optional per-benchmark strategies.

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

The command checks everything, queues the experiment and returns; the experiment runs in the background and its output goes to `experiments/logs/EXP_NAME.log` (see "How experiments run").

Flags:

- `--config`: path to the configuration file from step 1.
- `--experiment-name`: name of this run. Results are stored under `<experiment_filestore>/EXP_NAME`. Use a new name for every run; the run stops if a folder with that name already exists. Required, unless an experiment file gives `experiment_name` (the flag wins if both are given).
- `--fuzzers`: list of fuzzers to run. Each name must match a folder name in `fuzzers/` (aflplusplus, carpetfuzz, configfuzz, libafl, prophetfuzz, vafuzz, zigzagfuzz). Required unless `--experiment` is given.
- `--benchmarks`: list of benchmarks to run. Each name must match a folder name in `benchmarks/` (for example `libxml2_xmllint`). Required unless `--experiment` is given.
- `--compiletime`: list of compile-time configuration strategies. Each name must match a folder name in `compiletime/` (default, manual, maximum, minimum, pairwise, randomsmart). Optional; if left out, only `default` is used.
- `--runtime-strategy`: list of run-time configuration strategies. Each name must match a folder name in `runtime/` (default, pairwise, random, mostenabled, mostdisabled, diversity). Optional; if left out, only `default` is used. See "Runtime strategies" below.
- `--bug-triaging`: list of crash triage tools to run after fuzzing. Each name must match a folder name in `bug-triaging/` (afl-collect). Optional; if left out, no triage is run.
- `--no-superc`: optional. Turns off the SuperC presence-condition analysis that otherwise runs at the end of the experiment.
- `--experiment FILE` (or `--groups FILE`): optional. Reads what to run from an experiment file instead of `--fuzzers`, `--benchmarks`, `--compiletime` and `--runtime-strategy` (giving any of those with it is an error). See "Experiment files" below.
- `--dry-run`: optional. Checks the configuration, the experiment and every name, prints the planned runs, builds, trials and the estimated duration, and exits. Nothing is built, copied, queued or run, so it is safe to use while another experiment is running.
- `--foreground`: optional, rarely needed. Runs the experiment in this process, attached to the terminal, instead of queueing it; the output still goes to `experiments/logs/EXP_NAME.log` too. The queue starts every experiment this way. By hand it does not wait for other experiments, and closing the terminal stops it.

### Interactive setup

Run it with no flags, in a terminal:

```bash
python3 common/run_experiment.py
```

It asks, one question at a time (arrow keys to move, space to tick, enter to continue, Ctrl-C to cancel):

1. The config file (default `config.yaml`) and the experiment name. A name already in the result folders, queued or running is asked again.
2. Same benchmarks for the whole experiment, or different benchmarks for different fuzzers.
3. The strategies, then the engine (fuzzer underneath) of each. A strategy with one engine is not asked:

   | Strategy | Engines | Runs as |
   |---|---|---|
   | default | aflplusplus, libafl | that fuzzer with the benchmark's command line |
   | random, pairwise, diversity, mostenabled, mostdisabled | aflplusplus, libafl | that fuzzer with that runtime strategy |
   | carpet | carpetfuzz | `carpetfuzz` |
   | prophet | carpetfuzz | `prophetfuzz` |
   | variability aware | aflplusplus | `vafuzz` |
   | config based | aflplusplus | `configfuzz` |
   | zigzag | zigzagfuzz | `zigzagfuzz` |

   Runtime strategies come from `runtime/` and their engines from the fuzzers that support them (`runtime/supported_fuzzers.json`), so a new one is offered without changing the setup.
4. The benchmarks (once, or for each fuzzer), each followed by its compile-time strategies (`default` ticked). Benchmarks a choice cannot run on (a missing grammar, dictionary or CarpetFuzz file) are shown greyed out with the reason. The rules are the web app's (`webapp/catalog.py`), which match the checks of `run_experiment.py`.
5. Cores (saved as `cores_to_use` in the file), trials and fuzzing time per trial (`900`, `15m`, `24h`, `1h30m`). With different benchmarks per fuzzer, trials and time can also differ per fuzzer.
6. SuperC and bug triaging. **These answers are saved but not applied yet** (under `not_applied` in the file); the experiment runs without SuperC and without triage.

The answers are saved as `experiments/<name>.yaml` and checked with `--dry-run`, which prints the planned runs and the estimated duration. Then you choose: add it to the queue (it runs in the background, also after the terminal is closed, and shows up in the web app), only keep the file, or cancel (deletes the file). After queueing it can follow the log for you; Ctrl-C then stops following, not the experiment. A kept file is queued later with:

```bash
python3 common/run_experiment.py --config config.yaml --experiment experiments/<name>.yaml
```

### How experiments run

Every experiment, however it is started (flags, an experiment file, the interactive setup or the web app), goes through one job queue, `common/jobs.py`:

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

  `queued` and `stop_command` are written when it is queued, `started` and `estimated_end` when it starts. A copy is kept in the experiment folder as `experiment.yaml`. The file runs again with `--experiment` (with a new `experiment_name`).
- **The estimated end** adds the build time of every image (base and runner images, fuzzers, benchmark copies and coverage builds, `build_parallelism` at a time, from fixed per-build times in `experiment_plan.estimate_seconds`), the trials packed onto `cores_to_use` cores with a few minutes of coverage replay each, and a few minutes at the end. Images that already exist are not rebuilt, so experiments usually end earlier. `--dry-run` prints the same estimate.

Commands:

```bash
python3 common/jobs.py list                # the queue and recent jobs, with their logs
python3 common/jobs.py stop EXP_NAME       # cancel a queued experiment, or stop a running one
tail -f experiments/logs/EXP_NAME.log          # follow an experiment
```

Stopping kills the experiment's processes and every trial container labelled `fbpp.experiment=<name>`; finished trials are kept (the same as **Stop experiment** in the web app). `jobs.py` reads the result folders from `config.yaml`; give `--config FILE` before the command for another one.

### Full command

Example that runs every fuzzer on every benchmark with every compile-time strategy, crash triage and SuperC analysis:

```bash
python3 common/run_experiment.py \
  --config config.yaml \
  --experiment-name EXP_NAME \
  --fuzzers aflplusplus carpetfuzz configfuzz libafl prophetfuzz vafuzz zigzagfuzz \
  --benchmarks binutils_nm-new binutils_objdump bison_bison expat_xmlwf ffmpeg_ffmpeg file_file libpng_pngimage libtiff_tiff2pdf libxml2_xmllint pcre2_pcre2test x264_x264 xz_xz \
  --compiletime default manual maximum minimum pairwise randomsmart \
  --runtime-strategy default pairwise random mostenabled mostdisabled diversity \
  --bug-triaging afl-collect
```

### Experiment files

With command-line flags, every fuzzer runs on every benchmark with every listed strategy. An experiment file (`--experiment FILE`, or `--groups FILE`; both names do the same) says exactly what to run instead:

- **groups** choose which fuzzers run on which benchmarks, each group with its own strategies, number of trials and fuzzing time;
- an optional **`benchmarks` section** sets the strategies of a benchmark once, for every group that runs it.

The machine settings (cores, memory, result folders, `random_seed`, ...) and the default `trials` and `max_total_time` still come from `config.yaml`.

```bash
python3 common/run_experiment.py \
  --config config.yaml \
  --experiment experiment.yaml
```

The file is YAML, or JSON if its name ends in `.json` (same keys). Experiment files are your own and are not tracked: `experiment.yaml` in the project root is in `.gitignore`, so copy the example below into it and edit it. A commented example:

```yaml
# Name of the experiment (results go to <experiment_filestore>/<experiment_name>).
# Optional if you pass --experiment-name, which overrides it.
experiment_name: vafuzz_vs_zzf

# Optional, default false. Same as --no-superc (either one turns SuperC off).
no_superc: true

# Optional, default: no triage. Crash triage tools from bug-triaging/.
# --bug-triaging on the command line overrides this list.
bug_triaging: [afl-collect]

# Required: one or more groups. Within a group, every fuzzer runs on every benchmark
# with every compile-time and runtime strategy of that group. The experiment is all
# groups together; fuzzers and benchmarks of different groups are not combined.
groups:
  # vafuzz on six benchmarks, with trials and max_total_time from config.yaml.
  - fuzzers: [vafuzz]                      # required: folder names in fuzzers/
    benchmarks: [binutils_objdump, libxml2_xmllint, xz_xz,
                 pcre2_pcre2test, libtiff_tiff2pdf, bison_bison]   # required: folder names in benchmarks/

  # zigzagfuzz on two of them only, with its own trials and fuzzing time.
  - fuzzers: [zigzagfuzz]
    benchmarks: [binutils_objdump, libxml2_xmllint]
    trials: 1                              # optional: replaces trials from config.yaml for this group
    max_total_time: 3600                   # optional: replaces max_total_time (seconds) for this group

  # aflplusplus with two compile-time and two runtime strategies.
  - fuzzers: [aflplusplus]
    benchmarks: [xz_xz, pcre2_pcre2test]
    compiletime: [default, minimum]        # optional, default [default]: folder names in compiletime/
    runtime_strategy: [default, pairwise]  # optional, default [default]: folder names in runtime/

# Optional: strategies of a benchmark in every group that runs it. A key given here
# replaces that group key for this benchmark only; a key left out keeps the group's.
benchmarks:
  pcre2_pcre2test:
    compiletime: [default, maximum]
```

What this example runs (with `trials: 3` in `config.yaml`):

| Group | Runs | Trials |
|---|---|---|
| vafuzz | 5 benchmarks with `default`, plus pcre2 with `default` and `maximum` (from the `benchmarks` section): 7 runs | 3 each, from `config.yaml` |
| zigzagfuzz | objdump and xmllint with `default`: 2 runs | 1 each, of 3600 s |
| aflplusplus | xz: `default`, `minimum` x runtime `default`, `pairwise` = 4 runs; pcre2: `default`, `maximum` (the `benchmarks` section replaces the group's `minimum`) x 2 runtime = 4 runs | 3 each, from `config.yaml` |

`--dry-run` prints this list for any file (see below), so you can check a file before starting it.

#### Keys

| Key | Where | Required | Default | Meaning |
|---|---|---|---|---|
| `experiment_name` | top level | unless `--experiment-name` is given | none | Name of the experiment. `--experiment-name` overrides it. |
| `no_superc` | top level | no | `false` | `true` turns off SuperC, like `--no-superc`. |
| `bug_triaging` | top level | no | `[]` | Crash triage tools. `--bug-triaging` overrides it. |
| `cores_to_use` | top level | no | `cores_to_use` in `config.yaml` | Cores for this experiment, replacing `config.yaml`'s. |
| `not_applied` | top level | no | none | Ignored. The interactive setup saves its SuperC and triage answers here until they are supported. |
| `groups` | top level | yes | none | List of groups (at least one). |
| `fuzzers` | group | yes | none | Fuzzers of this group. |
| `benchmarks` | group | yes | none | Benchmarks of this group (a list of names). |
| `compiletime` | group | no | `[default]` | Compile-time strategies of this group. |
| `runtime_strategy` | group | no | `[default]` | Runtime strategies of this group (see "Runtime strategies"). |
| `trials` | group | no | `trials` in `config.yaml` | Trials of each run in this group. |
| `max_total_time` | group | no | `max_total_time` in `config.yaml` | Fuzzing time per trial in seconds; split over the compile-time copies of a benchmark, as in `config.yaml`. |
| `benchmarks` | top level | no | none | A mapping from benchmark name to its settings (below). Not to be confused with a group's `benchmarks` list. |
| `benchmarks.<name>.compiletime` | top level | no | the group's | Compile-time strategies of this benchmark in every group that runs it. |
| `benchmarks.<name>.runtime_strategy` | top level | no | the group's | Runtime strategies of this benchmark in every group that runs it. |

A list with one name can also be written as a plain name (`fuzzers: vafuzz`). `runtime-strategy` is accepted for `runtime_strategy` (not both in one place).

#### Which setting wins

- **Strategies** of a run: the `benchmarks` section if it sets that key for the benchmark, else the group's key, else `[default]`.
- **Trials and fuzzing time** of a run: the group's `trials`/`max_total_time`, else `config.yaml`. The `benchmarks` section cannot set them.
- **Name, SuperC and triage**: the command-line flag, else the file.

#### How a file becomes runs

- A **run** is one fuzzer on one benchmark with one compile-time and one runtime strategy. Each group adds fuzzers x benchmarks x compile-time strategies x runtime strategies runs, and each run has `trials` trials of `max_total_time` seconds.
- The same run listed in two groups runs once if both give it the same `trials` and `max_total_time`; if they differ, the experiment stops with an error naming both groups.
- **Nothing that cannot run is run, skipped or replaced.** Every run is checked before anything is built, and if any run cannot run, the experiment stops and lists every such run with the reason and where it came from (its group, or the `benchmarks` section). This applies the same way to experiment files and to command-line flags. A run cannot run when:
  - it asks for a non-default runtime strategy with a fuzzer that does not support one. Only the fuzzers in `runtime/supported_fuzzers.json` (aflplusplus, libafl) do, so put other fuzzers in a group with `runtime_strategy: [default]`, and do not set a `benchmarks` runtime strategy for a benchmark that such a fuzzer runs;
  - it asks for a non-default runtime strategy on a benchmark without `rt_grammar.json`;
  - its benchmark has no `ct_grammar.json`, which every compile-time strategy needs;
  - its fuzzer needs a benchmark file that is missing, as listed in `fuzzers/benchmark_requirements.json` (for example `dict` for zigzagfuzz, `rt_grammar.json` for vafuzz, the CarpetFuzz analysis for carpetfuzz).
- A `benchmarks` entry for a benchmark that no group runs is an error, since its settings would not be used.
- Only what the runs need is built: each fuzzer is built only against the benchmark copies it runs on, and compile-time strategies and runtime configurations are generated only for the benchmarks that use them.
- Every name, key and value is checked before anything is built: a misspelled key, an unknown fuzzer, benchmark, strategy or triage tool, or a `trials`/`max_total_time` that is not a positive integer stops the experiment with an error.
- Trials are queued on the cores from `config.yaml` (`cores_to_use`, `first_core`, `allow_serial_execution`) whatever group they come from.
- A copy of the experiment file is saved in the experiment folder as `experiment.yaml` (or `.json`). Runs started with flags save their single group there in the same format, so every experiment records what it ran.
- Result folders are named as before (`<fuzzer>[_rts_<strategy>]_cts_<strategy>_<benchmark>_<n>_trial_<k>`), so `common/post_analysis.py` and the report scripts work the same.

Check a file with `--dry-run` before starting it. It prints every run with its trials and time, the number of builds and trials, and the total fuzzing hours:

```bash
python3 common/run_experiment.py --config config.yaml --experiment experiment.yaml --dry-run
```

Two experiments never run at the same time from one checkout: they would share the benchmark copies in `benchmarks/cts_*`, the coverage images and the cores. The queue starts the next one when the previous one has finished (see "How experiments run").

### Redoing the coverage of a finished experiment

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

### Web app

`webapp/` is a browser front end for the same workflow, from configuring an experiment to reading its results. It starts the same commands as this README (`run_experiment.py` with an experiment file, and `post_analysis.py`) and reads the files they write. You can use the web app and the command line side by side.

#### Starting it

Start the app on the fuzzing machine, from the root of the project:

```bash
python3 webapp/app.py --config config.yaml                 # http://127.0.0.1:8800/
mkdir -p experiments/logs && setsid nohup python3 webapp/app.py --config config.yaml \
  > experiments/logs/webapp.log 2>&1 < /dev/null &            # or in the background
```

Options:

- `--config`: the configuration file. The default is `config.yaml`.
- `--port`: the port. The default is 8800.
- `--host`: the address to listen on. The default is localhost only.
- `--token`: a secret the app asks for (also read from `FBPP_WEBAPP_TOKEN`).

**Access.** Anyone who can reach the app can run Docker containers, which is root-equivalent, so it listens on localhost only. From another computer, tunnel the port over SSH and open http://localhost:8800/:

```bash
ssh -L 8800:localhost:8800 <fuzzing-machine>
```

The app only listens on other addresses (`--host 0.0.0.0`) when started with `--token SECRET`. Each browser then opens it once with `?token=SECRET`, and a cookie keeps it signed in.

**Before the first experiment**, run `run_as_sudo.sh` as root. The Experiments page shows a red check when `core_pattern` is not `core` or the CPU governor is not `performance`. Experiments still run without these settings, but AFL++ warns, and the coverage numbers are noisier.

#### Running an experiment

1. **Open New experiment.** Give the experiment a name; it becomes the folder name, so use letters, digits, `.`, `_` and `-`. Choose any crash triage, and whether to run SuperC.
2. **Fill in one or more groups.** Each group runs every chosen fuzzer on every chosen benchmark, with every chosen compile-time and runtime strategy (see "Experiment files" above).
   - **Fuzzer chips:** "runtime strategies" marks the fuzzers that can use a non-default runtime strategy.
   - **Benchmark chips:** "no rt grammar" marks the benchmarks that cannot use one.
   - **Trials and fuzzing time:** leave them empty to use `config.yaml`.
   - **Warnings:** a yellow box lists runs that cannot run, and the cost line shows the fuzzing hours.
3. **Check the experiment file** on the right. The form writes it as you go, and you can also edit it directly, for example to add a top-level `benchmarks` section. After a hand edit the form stops overwriting the file; "rewrite from the form" switches it back.
4. **Click Preview (dry run).** This runs `run_experiment.py --dry-run` on the file, which checks every name and combination without building anything. A green box means the experiment can run; it is followed by the trials, the fuzzing hours, the shortest possible run time on your cores, the builds, and one row per run. A red box shows the dry run's errors.
5. **Click Queue experiment.** You can only queue after a preview passes, and after any change you have to preview again. The file is saved to `experiments/<name>.yaml`, as for an experiment queued from a terminal, and the log to `experiments/logs/<name>.log`. The browser then opens the experiment's page, which shows the saved file with its record.

Jobs (experiments and post-analyses) go into the same queue as experiments queued from a terminal and run **one at a time** (see "How experiments run"). Jobs run as their own processes, so they keep going if the web app is stopped or restarted, and the background worker starts queued jobs while the web app is down. **Run again…** on an experiment's page opens the form with that experiment's file and a new name.

#### Reading the pages

**Experiments** (the home page):

- **Checks:** a row of host checks, red when something needs attention.
- **Running and queued:** what is running or waiting, including experiments started from a terminal.
- **All experiments:** every experiment in the experiment filestore, with its status, its progress (trials done out of planned, and failures in red) and a link to its statistics. The status is one of:
  - **queued:** waiting for the machine.
  - **running:** with its current phase.
  - **finished:** the experiment reached its end.
  - **stopped:** it ended early, because it failed or was stopped.
  - **incomplete:** an experiment from before `events.jsonl` existed that has fewer coverage reports than planned trials.

**An experiment's page:**

- **Header:**
  - The trials done, running and failed; the time elapsed; and, while fuzzing, an estimate of the time left from the trials finished so far.
  - The phases in order: building images, building benchmarks, fuzzing, aggregating, SuperC, triage, statistics. The current phase is highlighted.
  - **Stop experiment:** shown while the experiment runs. It kills the experiment's processes and every trial container labelled `fbpp.experiment=<name>`. Finished trials are kept, and the experiment then shows as stopped.
- **Trials:** one row per planned trial, which you can filter by status or benchmark. Each row has the arm (`fuzzer[strategy]`), benchmark, compile-time strategy, status, core, duration, the branches and lines covered (covered / instrumented, %, from the trial's `coverage/report.txt`) and a link to the trial's log. The status is one of:
  - **queued:** not started yet.
  - **running:** on the core shown.
  - **success:** fuzzing and coverage finished.
  - **failure:** the trial's log says why.
  - **skipped:** its coverage binary did not build.
  - **interrupted:** it started but the experiment stopped.
- **Log:** the experiment's log, updating live with "follow" on. The menu also shows the log of each post-analysis job.
- **Results:** the statistics report embedded in the page, with links to open it in a new tab and to its CSV files (see "Statistics report" below).
- **Post-analysis:** queues `post_analysis.py` on a finished experiment:
  - **Statistics report:** the metric to rank by, the baseline fuzzer, and optionally another experiment for the reproducibility section.
  - **Per-configuration coverage:** runtime strategies only. Needed before the "union against best single configuration" table.
  - **Crash triage:** only when the experiment built a triage tool.

  Below the options, the experiment's jobs are listed with their status and exit code.
- **Experiment file:** the file the experiment ran with.

For a first look at results: start with **Overall ranking** in the report, then each benchmark's **Against the default** table, which has the most statistical power. Then use the box plots to see how much the trials vary. Read "Limits of the analyses" below before quoting a p-value or a critical-difference diagram.

#### Files

- `webapp/instance/`: the job queue shared with the command line (`jobs.db` and its lock files) and dry-run scratch files. It is not tracked by git. Deleting it empties the queue and the job history; experiments, experiment files and reports are kept.
- `experiments/<name>.yaml`: every experiment's file with its record, and `experiments/logs/`: every log (see "How experiments run"). The `experiments/` folder is not tracked by git.
- `<experiment>/events.jsonl`: written by `run_experiment.py`. It records the phases, each trial's start and end with its core and status, and the end of the experiment. Experiments from before this file existed still show, with their progress counted from the coverage reports.
- `run_experiment.py --dry-run --plan-json FILE`: writes the dry-run plan as JSON. The preview uses it.
- `webapp/static/`, `webapp/templates/`: the pages. They are plain HTML, CSS and JavaScript, with no build step and no external scripts.

### Statistics report

At the end of every experiment, `common/statistical_analysis.py` compares the experiment's arms and writes `<report_filestore>/EXP_NAME/statistics/index.html`, with CSV tables (`trials.csv`, `benchmark_ranking.csv`, `overall_ranking.csv`, `pairwise_tests.csv`) next to it. An arm is a fuzzer under one runtime strategy, written `fuzzer[strategy]` (`{cts:...}` is added for a non-default compile-time strategy). The report gives a ranking per benchmark and an overall ranking, and has these parts:

- **Per benchmark:** median, minimum, maximum, IQR and CV of the final coverage, plotted as box plots. Two-sided Mann-Whitney U with Vargha-Delaney A12 against the default runtime strategy and the baseline fuzzer. Kruskal-Wallis with Dunn's test. Pairwise p-value and A12 heatmaps. The one-sided better-than matrix with wins. Unique, pairwise-unique and Jaccard coverage, and an UpSet plot.
- **Across benchmarks:** average rank, average normalized score, first places, unique-coverage rankings, Friedman with a Nemenyi critical-difference diagram, and correlations between rankings. Each is given for all arms, for each fuzzer's runtime strategies, and for the fuzzers under their default strategy.
- **Other tables:** relative coverage, benchmark properties, found bugs (from afl-collect), and minimum achievable p-values with low-sample flags.

Every pairwise table uses Holm correction. Coverage comes from each trial's `coverage/report.txt`, and covered sets from `coverage/report.json`. To run the report on a finished experiment:

```bash
python3 common/post_analysis.py --state /path/to/experiment-data/EXP_NAME/experiment_state.pkl --stats
```

Options:

- `--metric lines|branches|regions|functions`: the metric to rank by. The default is `branches`.
- `--baseline FUZZER`: the fuzzer the other fuzzers are compared against. The default is `aflplusplus`.
- `--compare-to /path/to/other/experiment`: adds a reproducibility section, with the rank correlation and changes in significance between the two experiments. Use it for a repeated run, or for a run with one setting changed.
- `--per-config-coverage`: first writes one coverage report per runtime configuration (with Docker), so that the report can compare each trial's union over configurations with its best single configuration.
- `--stats-html`: also writes an llvm-cov HTML source report for every arm and benchmark, from the arm's merged trial profiles, to `statistics/html/<benchmark>/<arm>/index.html` (as FuzzBench's coverage reports). Only the source files the coverage build uses are copied out of its Docker image, into `statistics/html/src/` (`common/coverage_html.py`). Arms whose trials ran on several benchmark copies (a compile-time strategy with many configurations) are skipped, since their profiles cannot be merged.

#### Limits of the analyses

Some analyses are computed, but do not mean what their names suggest for typical FuzzBench++ experiments. The report warns at the top when items 1 and 2 apply. The numbers below are from a test run with 5 arms (aflplusplus with 4 runtime strategies, and zigzagfuzz), 2 benchmarks and 5 trials of 300 s.

1. **Full pairwise heatmaps need many trials.** With n trials per arm, an exact two-sided Mann-Whitney U test cannot go below 2 / C(2n, n): 0.1 for 3 trials and 0.008 for 5. Holm multiplies the smallest p-value by the number of pairs. With 5 trials and 5 arms (10 pairs), no cell of the two-sided heatmap can reach p < 0.05, whatever the data.
   - **What has power:** the **Against the default** table only compares each runtime strategy with its fuzzer's default, and each fuzzer with the baseline, so Holm covers a few tests. There, 5 trials can show a significant difference.
   - **Recommendation:** use that table as the main test, and plan 10 or more trials before reading the full heatmaps.
   - **The better-than matrix:** it can show wins where the two-sided heatmap cannot, because a one-sided test has half the p-value floor.
   - **Dunn's test:** it has the same problem as the heatmaps.
2. **The Friedman test and the Nemenyi critical-difference diagram need many benchmarks.** The critical difference shrinks with the square root of the number of benchmarks. With 2 benchmarks and 5 arms it is 4.31 ranks, wider than the whole rank range, so the diagram joins every arm in one group.
   - **What is still valid:** the average ranks, normalized scores and first places.
   - **What needs more benchmarks:** the significance of the ranking. Expect it to separate arms only with most of the 12 benchmarks.
3. **Correlations between rankings are computed over the arms**, usually 3–5 values. Their p-values tell nothing at that size, and the report gives exact permutation p-values to make that visible. Read ρ and τ as descriptions, not tests.
4. **Unique coverage rewards variance.** It is computed on the union of all of an arm's trials. An arm whose trials differ a lot (as multi-configuration runtime strategies do) collects a large union even when its typical trial is weak. On objdump, `random` had the lowest median (1,984 branches) and close to the largest union (4,632). Unique coverage is also only comparable between arms with the same number of trials (see the low-sample flag).
5. **"Union against best single configuration" is not a comparison with a single configuration.** A runtime strategy fuzzes its configurations one after another, each starting from the previous corpus. A configuration's report only replays the inputs first found under it, with its own options. Its "best single" value is therefore that configuration's share of the trial, not what it would reach running alone for the whole time. To compare with single configurations, run them as separate experiments. Also, with 300 s and `min_config_time` 60 s, a trial fuzzes at most 5 configurations, and those without new inputs are left out.
6. **Found bugs cannot be split by runtime strategy.** Crash triage pools the crashes of a fuzzer's trials per benchmark. `run_triaging` also reads only `<fuzzer>_<benchmark>_trial_*` folders, so trials under a runtime strategy (`<fuzzer>_rts_<strategy>_...`) are not triaged at all. Until that is changed, the table counts the default runtime strategy only. Treat it as a secondary metric in any case: crashes are sparse, and one bug reached through different stacks can count more than once.
7. **The benchmark properties table has no input format.** Nothing in `benchmarks/<name>/` records it, so the column is left out.
8. **Reproducibility and sensitivity need a second experiment.** `--compare-to` gives the rank correlation and the significance changes against another experiment. The other experiment can be a repeat with the same file (reproducibility), or a run with one setting changed, such as seeds, dictionary or a longer time (sensitivity). Both experiments need the same arms and benchmarks.
9. **Host settings affect every number.** Without `run_as_sudo.sh` (CPU governor `powersave`, `core_pattern` not `core`), trials vary more, which weakens every test above. The web app's Experiments page shows both settings.

`python3 common/statistical_analysis.py EXPERIMENT_PATH -o OUT_DIR [--metric ...] [--html]` does the same without an experiment state (`--html` as `--stats-html`).

### vafuzz coverage

VAFuzz runs every input under a batch of command-line option configurations and saves, for each queue entry, the configurations it ran it with (`default/queue_argvs/id:<N>_<k>`, `+cov` on those that found new edges). Its `coverage.py` replays each queue entry once per saved configuration, with the options placed between the program and its own arguments as the fuzzer's target does; entries without saved configurations (the seeds) run without options. `VAFUZZ_COVERAGE_ARGVS=cov` replays only the `+cov` configurations, which gives the same coverage much faster. `VAFUZZ_COVERAGE_TIMEOUT` (seconds, default 30) limits each execution. Set them in the environment of `run_experiment.py` or `rerun_coverage.py`; they are passed on to the coverage container.

## Runtime strategies

A runtime strategy fuzzes a benchmark under several run-time configurations
(command-line options) instead of the single command in its `run_target.sh`. It
applies to the fuzzers listed in `runtime/supported_fuzzers.json` (aflplusplus,
libafl); asking for one with any other fuzzer stops the experiment with an error.
Each strategy reuses the fuzzer's normal benchmark build, so it only adds trials,
not builds.

| Strategy | Configurations, built from the benchmark's `rt_grammar.json` |
|---|---|
| `default` | none: the normal run with `run_target.sh` |
| `pairwise` | a 2-way covering array: every pair of option values appears together at least once |
| `random` | 50 random valid configurations |
| `diversity` | 50 valid configurations chosen to be as different as possible (Hamming distance) |
| `mostenabled` | 1 configuration with as many options on as the grammar's constraints allow |
| `mostdisabled` | 1 configuration with every option off |

How a run works:

1. Before trials start, `common/rt_config_generator.py` runs `runtime/<strategy>/strategy.py`
   for every strategy, benchmark and trial, and writes the shuffled configurations to
   `<experiment>/rt_configs/<strategy>/<benchmark>/trial_<k>.json`. The order depends on
   `random_seed`, the strategy, the benchmark and the trial, so trials differ, runs are
   reproducible, and all supported fuzzers get the same configurations.
2. The trial container gets that file and `MULTI_CONFIG=1`, and runs
   `runtime/multi_config_run.sh`: the configurations are fuzzed one after another, each for an
   equal share of the trial's time (at least `min_config_time` seconds), each starting from the
   previous configuration's corpus. The fuzzer's own `run.sh` is called once per configuration.
3. `runtime/multi_config_coverage.sh` replays each input under the configuration that found it,
   using the fuzzer's own `coverage.py`, and merges everything into one report per trial.

Results are stored as `<fuzzer>_rts_<strategy>_<benchmark>_trial_<k>` (default runs keep their
usual names) and are reported as `<fuzzer>[<strategy>]`.

Options listed in a grammar's `exit_options` are never used by the strategies: with them the
target exits without processing its input (help, version, listings, or a schema/DTD file that
does not exist), so every configuration containing one would fuzz nothing.

To add a strategy, add `runtime/<name>/strategy.py` with a `request_configurations(grammar, rng)`
function that returns a list of argument lists (see `runtime/rt_common.py`). To support another
fuzzer, add it to `runtime/supported_fuzzers.json` with the folder its corpus is written to, and
make its `run.sh` read seeds from `${SEED_DIR:-/benchmark/seed}`.

## Tests

```bash
python3 -m pytest tests
```
