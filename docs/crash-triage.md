# Crash triage

[ConfigFuzzEval](../README.md) › [Documentation](README.md) › Crash triage

## Triagers

`bug_triaging: [gdb-exploitable]` in an [experiment file](run-experiment-file.md) (or `--bug-triaging gdb-exploitable afl-collect`, ... on the [command line](run-command-line.md)) triages every trial's crashes at the end of the experiment; on a finished experiment that built the triagers, `post_analysis.py --state ... --triage` does it again. There are two triagers; both use gdb and the [exploitable](https://github.com/jfoote/exploitable) gdb plugin, and both replay each crash with the command line it was found with (`bug-triaging/crash_commands.py`, see [Replaying a crash](#replaying-a-crash)). They differ in what counts as one bug:

| Triager | Tool | One bug is |
|---|---|---|
| `gdb-exploitable` | `triage.py`: gdb + exploitable at a fixed commit | the same crash state: the signal and the top 3 stack frames in the program (frames in libc and other libraries are skipped), as FuzzBench counts bugs |
| `afl-collect` | [afl-collect](https://github.com/rc0r/afl-utils) (afl-utils at a fixed commit), with its exploitable copy patched for gdb 12 | the same exploitable major hash (more frames, so usually more bugs: 4 instead of 1 on the 24-hour xmllint crashes) |

afl-collect replays every crash of a folder with one command, written into a gdb script and run through a shell, which changes fuzzed arguments (bytes that are not text, spaces, empty arguments) and turns every `@@` into the crash. So its target is `bug-triaging/afl-collect/launcher.py @@`, which looks each crash's command line up and replaces itself with the program and its exact arguments; gdb follows the exec, so afl-collect classifies the program's crash. On the 38 crashes of the 24-hour ZigZagFuzz runs, afl-collect without the launcher lost 13 (non-text arguments) and with it handled all 38.

## Replaying a crash

- **Each crash is replayed with the command line it was found with**, on the trial's coverage build, under gdb, without a shell, so fuzzed arguments reach the program byte for byte. Fuzzers that change the command line save it differently, and `crash_commands.py` reads it as the fuzzer's `coverage.py` does:

  | Fuzzer | Command line of a crash |
  |---|---|
  | aflplusplus, libafl | the benchmark's `run_target.sh` |
  | zigzagfuzz | `default/crashes_argvs/id:<N>`, the full argv |
  | carpetfuzz, prophetfuzz | the `argv:<N>` in the crash's name, a line of the ranked commands |
  | vafuzz | `default/crashes_argvs/id:<N>_<k>`, every configuration it crashed under (tried in turn) |
  | configfuzz | the options encoded in the input, decoded by ConfigFuzz's printer |

  A [runtime-strategy](../README.md#runtime-strategies) trial's crashes (`config_<i>/default/crashes/`) run with the configuration they were found under. Replayed with the benchmark's fixed command line instead, none of the 38 crashes of the 24-hour ZigZagFuzz runs on objdump and xmllint crashed again; with their own argv, 37 did.
- **Classification and bugs:** exploitable's classification (EXPLOITABLE, PROBABLY_NOT_EXPLOITABLE, ...) is kept with every crash. gdb-exploitable records a crash that does not crash again, or runs longer than 30 s, as `NOT_REPRODUCED` or `TIMEOUT`; afl-collect drops it (`-r`). Neither is counted.
- **Results** are pooled per fuzzer, runtime strategy and benchmark copy, in `<experiment>/bug-triaging/<triager>/output/<run label>_<copy>/`: `crashes.db` (afl-collect's table `Data` for both: every crash with its classification and bug key in `Hash`), `pool.json` and a log per trial. gdb-exploitable adds, in `User_Comment`, the command, configuration, signal and crash state, and `bugs/<key>/` with the first crash of every bug (`input`, `command.txt`, the exact `argv`, `crash_state.txt`, `gdb.txt`); afl-collect adds `collection/` with the crashes it kept. The [statistics report](statistics-report.md) counts the bugs per arm (`fuzzer[strategy]`) and benchmark, one table per triager.

Triage runs as root in its container, to read the fuzzers' root-owned output (mounted read-only), and gives its results to the user who started it.

## See also

- [Statistics report](statistics-report.md): found bugs per arm, and why they are a secondary metric.
- [Post-analysis tab](web-app.md#post-analysis) of the web app, which triages a finished experiment again.
