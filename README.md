# FuzzBenchPlusPlus

## Build instructions

### 1. Create the configuration file

Create a file named `config.yaml` in the root of the project. Sample:

```yaml
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
experiment_filestore: /path/to/FuzzBenchPlusPlus/results/experiment-data
report_filestore: /path/to/FuzzBenchPlusPlus/results/report-data

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
```

### 2. Run an experiment

Optional: if you save the output to `logs-reports/` as in the commands below, create that folder first (it is not in the repository, and the given example command fails without it):

```bash
mkdir -p logs-reports
```

There are two ways to say what to run:

- **Command-line flags** (below): every fuzzer runs on every benchmark with every listed strategy, all with the `trials` and `max_total_time` from `config.yaml`.
- **An experiment file** (`--experiment`, see "Experiment files" below): groups of fuzzers and benchmarks, so specific fuzzers run on specific benchmarks, each group optionally with its own `trials` and `max_total_time`.

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
  --no-superc \
  > logs-reports/EXP_NAME.log 2>&1
```

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
- `--dry-run`: optional. Checks the configuration, the experiment and every name, prints the planned runs, builds and trials, and exits. Nothing is built, copied or run, so it is safe to use while another experiment is running.
- `> logs-reports/EXP_NAME.log 2>&1`: saves the full output of the run, including errors, to a log file in `logs-reports/` (see the `mkdir` step above).

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
  --bug-triaging afl-collect \
  > logs-reports/EXP_NAME.log 2>&1
```

### Experiment files

With command-line flags, every fuzzer runs on every benchmark. An experiment file instead lists **groups**: each group runs its own fuzzers on its own benchmarks, so you choose exactly which fuzzer runs on which benchmark, and each group can set its own number of trials and fuzzing time. The machine settings (cores, memory, result folders, `random_seed`, ...) still come from `config.yaml`.

```bash
python3 common/run_experiment.py \
  --config config.yaml \
  --experiment experiment.yaml \
  > logs-reports/EXP_NAME.log 2>&1
```

The file is YAML, or JSON if its name ends in `.json` (same keys). A commented example:

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
# groups together; groups do not combine with each other.
groups:
  # vafuzz on six benchmarks, with trials and max_total_time from config.yaml.
  - fuzzers: [vafuzz]                      # required: folder names in fuzzers/
    benchmarks: [binutils_objdump, libxml2_xmllint, xz_xz,
                 pcre2_pcre2test, libtiff_tiff2pdf, bison_bison]   # required: folder names in benchmarks/

  # zigzagfuzz on two of them only, with its own trials and fuzzing time.
  - fuzzers: [zigzagfuzz]
    benchmarks: [binutils_objdump, libxml2_xmllint]
    trials: 1                              # optional: overrides trials in config.yaml for this group
    max_total_time: 3600                   # optional: overrides max_total_time (seconds) for this group

  # aflplusplus with two compile-time and two runtime strategies:
  # 2 benchmarks x 2 compile-time x 2 runtime = 8 runs, each with `trials` trials.
  - fuzzers: [aflplusplus]
    benchmarks: [xz_xz, pcre2_pcre2test]
    compiletime: [default, minimum]        # optional, default [default]: folder names in compiletime/
    runtime_strategy: [default, pairwise]  # optional, default [default]: folder names in runtime/

# Optional: strategies for a benchmark in every group it is in. A key given here
# replaces the group's for that benchmark; a key left out keeps the group's.
benchmarks:
  xz_xz:
    compiletime: [default, maximum]
```

| Key | Where | Required | Default | Meaning |
|---|---|---|---|---|
| `experiment_name` | top level | unless `--experiment-name` is given | — | Name of the experiment. `--experiment-name` overrides it. |
| `no_superc` | top level | no | `false` | `true` turns off SuperC, like `--no-superc`. |
| `bug_triaging` | top level | no | `[]` | Crash triage tools. `--bug-triaging` overrides it. |
| `groups` | top level | yes | — | List of groups (at least one). |
| `benchmarks` | top level | no | — | Per benchmark, `compiletime` and/or `runtime_strategy` that replace the group's in every group with that benchmark. |
| `fuzzers` | group | yes | — | Fuzzers of this group. |
| `benchmarks` | group | yes | — | Benchmarks of this group. |
| `compiletime` | group | no | `[default]` | Compile-time strategies of this group. |
| `runtime_strategy` | group | no | `[default]` | Runtime strategies of this group (see "Runtime strategies"). |
| `trials` | group | no | `trials` in `config.yaml` | Trials of each run in this group. |
| `max_total_time` | group | no | `max_total_time` in `config.yaml` | Fuzzing time per trial in seconds; split over the compile-time copies of a benchmark, as in `config.yaml`. |

A list with one name can also be written as a plain name (`fuzzers: vafuzz`). `runtime-strategy` is accepted for `runtime_strategy`.

How a file becomes runs:

- A **run** is one fuzzer on one benchmark with one compile-time and one runtime strategy. Each group adds fuzzers x benchmarks x compile-time strategies x runtime strategies runs, and each run has `trials` trials of `max_total_time` seconds.
- The same run listed in two groups runs once if both give it the same `trials` and `max_total_time`; if they differ, the experiment stops with an error naming both groups.
- Only what the runs need is built: each fuzzer is built only against the benchmarks it runs on, and compile-time strategies and runtime configurations are generated only for the benchmarks that use them.
- A group may only ask for a non-default `runtime_strategy` with fuzzers listed in `runtime/supported_fuzzers.json`; otherwise the experiment stops with an error. (With `--runtime-strategy` on the command line, such fuzzers keep running the default strategy only, as before.)
- Every name, key and value is checked before anything is built: a misspelled key, an unknown fuzzer or benchmark, or a `trials`/`max_total_time` that is not a positive integer stops the experiment with an error.
- Trials are queued on the cores from `config.yaml` (`cores_to_use`, `allow_serial_execution`) whatever group they come from.
- A copy of the experiment file is saved in the experiment folder as `experiment.yaml` (or `.json`). Runs started with flags save their single group there in the same format, so every experiment records what it ran.
- Result folders are named as before (`<fuzzer>[_rts_<strategy>]_cts_<strategy>_<benchmark>_<n>_trial_<k>`), so `common/post_analysis.py` and the report scripts work the same.

Check a file with `--dry-run` before starting it. It prints every run with its trials and time, the number of builds and trials, and the total fuzzing hours:

```bash
python3 common/run_experiment.py --config config.yaml --experiment experiment.yaml --dry-run
```

To keep an experiment running after the terminal closes, start it detached:

```bash
setsid nohup python3 common/run_experiment.py \
  --config config.yaml \
  --experiment experiment.yaml \
  > logs-reports/EXP_NAME.log 2>&1 < /dev/null &
```

Do not run two experiments at the same time from one checkout: they share the benchmark copies in `benchmarks/cts_*`, the coverage images and, unless `first_core` in `config.yaml` keeps them apart, the cores. Put everything in one experiment file instead, or start the second when the first has finished.

## Runtime strategies

A runtime strategy fuzzes a benchmark under several run-time configurations
(command-line options) instead of the single command in its `run_target.sh`. It
applies to the fuzzers listed in `runtime/supported_fuzzers.json` (aflplusplus,
libafl); other fuzzers run with `default` only. Each strategy reuses the fuzzer's
normal benchmark build, so it only adds trials, not builds.

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
