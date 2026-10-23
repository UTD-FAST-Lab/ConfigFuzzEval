# Experiment files

[ConfigFuzzEval](../README.md) › [Documentation](README.md) › Experiment file

An experiment file says exactly what to run. It is one of the three ways to run an experiment, next to [command-line flags](run-command-line.md) and the [web app](web-app.md), which writes one too. You can write the file by hand, or let the [interactive setup](#writing-a-file-interactively) write it for you by asking questions in the terminal. Because a file can be kept in a repository and checked with `--dry-run`, it is also the way to run experiments from scripts and CI/CD pipelines.

## What a file contains

With [command-line flags](run-command-line.md), every fuzzer runs on every benchmark with every listed strategy. An experiment file (`--experiment FILE`, or `--groups FILE`; both names do the same) says exactly what to run instead:

- **groups** choose which fuzzers run on which benchmarks, each group with its own strategies, number of trials and fuzzing time;
- an optional **`benchmarks` section** sets the strategies of a benchmark once, for every group that runs it.

The machine settings (cores, memory, result folders, `random_seed`, ...) and the default `trials` and `max_total_time` still come from `config.yaml` (see [Installation](README.md#installation)).

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
bug_triaging: [gdb-exploitable]

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
    compiletime: [default, mostdisabled]        # optional, default [default]: folder names in compiletime/
    runtime_strategy: [default, pairwise]  # optional, default [default]: folder names in runtime/

# Optional: strategies of a benchmark in every group that runs it. A key given here
# replaces that group key for this benchmark only; a key left out keeps the group's.
benchmarks:
  pcre2_pcre2test:
    compiletime: [default, mostenabled]
```

What this example runs (with `trials: 3` in `config.yaml`):

| Group | Runs | Trials |
|---|---|---|
| vafuzz | 5 benchmarks with `default`, plus pcre2 with `default` and `mostenabled` (from the `benchmarks` section): 7 runs | 3 each, from `config.yaml` |
| zigzagfuzz | objdump and xmllint with `default`: 2 runs | 1 each, of 3600 s |
| aflplusplus | xz: `default`, `mostdisabled` x runtime `default`, `pairwise` = 4 runs; pcre2: `default`, `mostenabled` (the `benchmarks` section replaces the group's `mostdisabled`) x 2 runtime = 4 runs | 3 each, from `config.yaml` |

`--dry-run` prints this list for any file (see [Checking a file](#checking-a-file)), so you can check a file before starting it.

### Keys

| Key | Where | Required | Default | Meaning |
|---|---|---|---|---|
| `experiment_name` | top level | unless `--experiment-name` is given | none | Name of the experiment. `--experiment-name` overrides it. |
| `no_superc` | top level | no | `false` | `true` turns off [SuperC](superc.md), like `--no-superc`. |
| `bug_triaging` | top level | no | `[]` | [Crash triage](crash-triage.md) tools. `--bug-triaging` overrides it. |
| `cores_to_use` | top level | no | `cores_to_use` in `config.yaml` | Cores for this experiment, replacing `config.yaml`'s. |
| `not_applied` | top level | no | none | Ignored (written by earlier versions of the interactive setup). |
| `groups` | top level | yes | none | List of groups (at least one). |
| `fuzzers` | group | yes | none | Fuzzers of this group. |
| `benchmarks` | group | yes | none | Benchmarks of this group (a list of names). |
| `compiletime` | group | no | `[default]` | [Compile-time strategies](../README.md#compile-time-strategies) of this group. |
| `runtime_strategy` | group | no | `[default]` | Runtime strategies of this group (see [Runtime strategies](../README.md#runtime-strategies)). |
| `trials` | group | no | `trials` in `config.yaml` | Trials of each run in this group. |
| `max_total_time` | group | no | `max_total_time` in `config.yaml` | Fuzzing time per trial in seconds; split over the compile-time copies of a benchmark, as in `config.yaml`. |
| `benchmarks` | top level | no | none | A mapping from benchmark name to its settings (below). Not to be confused with a group's `benchmarks` list. |
| `benchmarks.<name>.compiletime` | top level | no | the group's | Compile-time strategies of this benchmark in every group that runs it. |
| `benchmarks.<name>.runtime_strategy` | top level | no | the group's | Runtime strategies of this benchmark in every group that runs it. |

A list with one name can also be written as a plain name (`fuzzers: vafuzz`). `runtime-strategy` is accepted for `runtime_strategy` (not both in one place).

### Which setting wins

- **Strategies** of a run: the `benchmarks` section if it sets that key for the benchmark, else the group's key, else `[default]`.
- **Trials and fuzzing time** of a run: the group's `trials`/`max_total_time`, else `config.yaml`. The `benchmarks` section cannot set them.
- **Name, SuperC and triage**: the command-line flag, else the file.

### How a file becomes runs

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
- Result folders are named as before (`<fuzzer>[_rts_<strategy>]_cts_<strategy>_<benchmark>_<n>_trial_<k>`), so `common/post_analysis.py` and the report scripts work the same (see [Result names](README.md#result-names)).

## Writing a file interactively

The interactive setup is the experiment file made easy: run `run_experiment.py` with no flags and it asks what to run, one question at a time (arrow keys to move, space to tick, enter to continue, Ctrl-C to cancel):

```bash
python3 common/run_experiment.py
```

It asks for the config file and the experiment name, then the fuzzers (each marked config-agnostic or config-aware), the [runtime strategies](../README.md#runtime-strategies) for the config-agnostic ones (config-aware fuzzers always run with `default`), the benchmarks with their [compile-time strategies](../README.md#compile-time-strategies), the cores, trials and fuzzing time, and [SuperC](superc.md) and [crash triage](crash-triage.md). It can use the same benchmarks for every fuzzer or different ones per fuzzer, which become groups. Benchmarks a fuzzer cannot run on are greyed out with the reason, by the same rules as the [web app](web-app.md).

The answers are saved as `experiments/<name>.yaml`, a file in the format above, and checked with `--dry-run`. Then you add it to the [queue](README.md#job-queue), only keep the file (to edit it or queue it later with `--experiment`), or cancel.

## Checking a file

Check a file with `--dry-run` before starting it. It prints every run with its trials and time, the number of builds and trials, and the total fuzzing hours:

```bash
python3 common/run_experiment.py --config config.yaml --experiment experiment.yaml --dry-run
```

Two experiments never run at the same time from one checkout: they would share the benchmark copies in `benchmarks/cts_*`, the coverage images and the cores. The queue starts the next one when the previous one has finished (see [Job queue](README.md#job-queue)).

An experiment file can also start a long-running campaign instead of a fixed-length evaluation: see [Continuous mode](README.md#continuous-mode).

## See also

- [Job queue](README.md#job-queue): the `record` that is added to every experiment's file, and following, listing and stopping it.
- [Experiments, runs, trials and arms](../README.md#experiments-runs-trials-and-arms) and the strategies, in the main README.
