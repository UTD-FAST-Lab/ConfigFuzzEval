# Interactive setup

[ConfigFuzzEval](../README.md) › [Documentation](README.md) › Interactive setup

The interactive setup is the easiest way to start: it asks what to run in the terminal, writes the answers as an [experiment file](run-experiment-file.md) and puts it in the [job queue](README.md#job-queue). The other ways are [command-line flags](run-command-line.md), an experiment file written by hand, and the [web app](web-app.md). Create `config.yaml` first (see [Installation](README.md#installation)).

## Starting it

Run it with no flags, in a terminal:

```bash
python3 common/run_experiment.py
```

It asks for the same things as the [command line](run-command-line.md) and the [web app](web-app.md) (fuzzers, runtime strategies, benchmarks and compile-time strategies), one question at a time (arrow keys to move, space to tick, enter to continue, Ctrl-C to cancel):

1. The config file (default `config.yaml`) and the experiment name. A name already in the result folders, queued or running is asked again.
2. Same benchmarks for the whole experiment, or different benchmarks for different fuzzers.
3. The fuzzers: every folder in `fuzzers/`, marked config-agnostic or config-aware (see [Fuzzers](../README.md#fuzzers)).
4. The [runtime strategies](../README.md#runtime-strategies) (`default` ticked), asked only when a config-agnostic fuzzer was chosen, and applied to those fuzzers. Config-aware fuzzers choose their own options and always run with `default`.
5. The benchmarks (once, or for each fuzzer), each followed by its [compile-time strategies](../README.md#compile-time-strategies) (`default` ticked). Benchmarks a fuzzer or runtime strategy cannot run on (a missing grammar, dictionary or CarpetFuzz file) are shown greyed out with the reason. The rules are the [web app](web-app.md)'s (`webapp/catalog.py`), which match the checks of `run_experiment.py`.
6. Cores (saved as `cores_to_use` in the file), trials and fuzzing time per trial (`900`, `15m`, `24h`, `1h30m`). With different benchmarks per fuzzer, trials and time can also differ per fuzzer.
7. [SuperC](superc.md) (`no_superc` in the file) and [crash triage](crash-triage.md) (`bug_triaging`).

The answers are saved as `experiments/<name>.yaml`, an [experiment file](run-experiment-file.md), and checked with `--dry-run`, which prints the planned runs and the estimated duration. Then you choose: add it to the [queue](README.md#job-queue) (it runs in the background, also after the terminal is closed, and shows up in the web app), only keep the file, or cancel (deletes the file). After queueing it can follow the log for you; Ctrl-C then stops following, not the experiment. A kept file is queued later with:

```bash
python3 common/run_experiment.py --config config.yaml --experiment experiments/<name>.yaml
```

## See also

- [Experiment file](run-experiment-file.md): the format of the file the setup writes, to edit or reuse it.
- [Job queue](README.md#job-queue): following, listing and stopping the experiment.
