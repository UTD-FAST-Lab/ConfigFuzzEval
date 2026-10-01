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

# true: if there are more trials than cores, queue the extra trials and run them
# as cores free up. false: stop if there are more trials than cores.
allow_serial_execution: true

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

Run from the root of the project:

```bash
python3 common/run_experiment.py \
  --config config.yaml \
  --experiment-name EXP_NAME \
  --fuzzers FUZZER1 FUZZER2 ... \
  --benchmarks BENCHMARK1 BENCHMARK2 ... \
  --compiletime STRATEGY1 STRATEGY2 ... \
  --bug-triaging TRIAGER1 ... \
  --no-superc \
  > logs-reports/EXP_NAME.log 2>&1
```

Flags:

- `--config`: path to the configuration file from step 1.
- `--experiment-name`: name of this run. Results are stored under `<experiment_filestore>/EXP_NAME`. Use a new name for every run; the run stops if a folder with that name already exists.
- `--fuzzers`: list of fuzzers to run. Each name must match a folder name in `fuzzers/` (aflplusplus, carpetfuzz, libafl, libfuzzer, libfuzzer_aflpp, libfuzzer_libafl, zigzagfuzz).
- `--benchmarks`: list of benchmarks to run. Each name must match a folder name in `benchmarks/` (for example `libxml2_xmllint`).
- `--compiletime`: list of compile-time configuration strategies. Each name must match a folder name in `compiletime/` (default, manual, maximum, minimum, pairwise, randomsmart). Optional; if left out, only `default` is used.
- `--bug-triaging`: list of crash triage tools to run after fuzzing. Each name must match a folder name in `bug-triaging/` (afl-collect). Optional; if left out, no triage is run.
- `--no-superc`: optional. Turns off the SuperC presence-condition analysis that otherwise runs at the end of the experiment.
- `> logs-reports/EXP_NAME.log 2>&1`: saves the full output of the run, including errors, to a log file in `logs-reports/` (see the `mkdir` step above).

### Full command

Example that runs every fuzzer on every benchmark with every compile-time strategy, crash triage and SuperC analysis:

```bash
python3 common/run_experiment.py \
  --config config.yaml \
  --experiment-name EXP_NAME \
  --fuzzers aflplusplus carpetfuzz libafl libfuzzer libfuzzer_aflpp libfuzzer_libafl zigzagfuzz \
  --benchmarks binutils_nm-new binutils_objdump bison_bison expat_xmlwf ffmpeg_ffmpeg file_file libpng_libfuzzerrunner libpng_pngimage libtiff_libfuzzerrunner libtiff_tiff2pdf libxml2_libfuzzerrunner libxml2_xmllint pcre2_pcre2test x264_x264 xz_xz \
  --compiletime default manual maximum minimum pairwise randomsmart \
  --bug-triaging afl-collect \
  > logs-reports/EXP_NAME.log 2>&1
```
