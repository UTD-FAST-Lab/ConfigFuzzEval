# Contributing

[ConfigFuzzEval](../README.md) › [Documentation](README.md) › Contributing

ConfigFuzzEval finds its plugins by folder name: a new benchmark is a folder in `benchmarks/`, a new fuzzer a folder
in `fuzzers/`. Once the folder is there, every way of running an experiment offers it: the
[command line](run-command-line.md), an [experiment file](run-experiment-file.md) (and the interactive setup that
writes one) and the [web app](web-app.md). This guide covers the two most common
contributions:

1. [Adding a benchmark](#part-1-adding-a-benchmark): a target program to fuzz.
2. [Adding a fuzzer](#part-2-adding-a-fuzzer), config-agnostic or config-aware.

Configuration strategies are added as described in [Adding a strategy](README.md#adding-a-strategy). Crash triage
tools and post-analysis tools are described on the web app's [Documentation page](web-app.md#documentation-page).
[Before you open a pull request](#before-you-open-a-pull-request) lists the checks to run.

## Part 1: Adding a benchmark

A benchmark is one program of one project, in `benchmarks/<project>_<program>/`, for example `xz_xz` or
`binutils_objdump`. Names starting with `cts_` or `coverage_` are reserved for the copies the framework makes.

### Directory layout

```
benchmarks/xz_xz/
├── builder.Dockerfile      builds the program, once per fuzzer and once for coverage
├── build.sh                configure and make, with {{CT_CONFIGURATION}} for compile-time options
├── run_target.sh           the command line that is fuzzed, @@ for the input file
├── seed/                   initial inputs, at least one file
├── ct_grammar.json         the ./configure options (compile-time strategies)
├── rt_grammar.json         the command-line options (runtime strategies, VAFuzz, ConfigFuzz)
├── superc_flags.txt        include directories and defines for SuperC
├── dict                    an AFL dictionary of the program's options (ZigZagFuzz)
├── manpage.1               the program's man page (input of CarpetFuzz's analysis)
├── carpetfuzz/             CarpetFuzz's analysis of the man page (CarpetFuzz)
└── ranked_stubs.txt        ranked option combinations (ProphetFuzz)
```

### Files

| File | Required | Contains |
|---|---|---|
| `builder.Dockerfile` | yes | How to download and build the program, and which files to copy out (below). A folder without it is not a benchmark. |
| `build.sh` | yes | The build commands. `{{CT_CONFIGURATION}}` on the `./configure` line is replaced by a compile-time strategy's options (empty for `default`). |
| `run_target.sh` | yes | One line: the program and its fixed arguments, with `@@` where the input file goes (for example `/benchmark/xz -d -c @@`). Without `@@`, the input is given on stdin. |
| `seed/` | yes | Initial inputs, at least one valid file. |
| `ct_grammar.json` | yes | The `./configure` options, their defaults and the constraints between them. Every compile-time strategy reads it, `default` too. |
| `rt_grammar.json` | for runtime strategies, VAFuzz and ConfigFuzz | The program's command-line options and the rules between them. |
| `superc_flags.txt` | for SuperC | `-I <dir>` and `-D NAME[=VALUE]` lines, as the build uses them (see [SuperC](superc.md#how-it-works)). |
| `dict` | for ZigZagFuzz | An AFL dictionary, one option per line (`-z`, `--format`, ...). |
| `manpage.1` | to generate CarpetFuzz's files | The program's man page, in roff format. |
| `carpetfuzz/` | for CarpetFuzz | `combinations.txt` and `dict.json`, made from `manpage.1` by `fuzzers/carpetfuzz/analysis/generate.sh <benchmark>`. |
| `ranked_stubs.txt` | for ProphetFuzz | Option combinations, ranked: a first line with their count, then one command per line with `@@` (for example `xz -d -f -7 -e @@`). |

### Which files each fuzzer needs

Every fuzzer needs the required files above. Some need more, listed in `fuzzers/benchmark_requirements.json`; a run on
a benchmark without them is refused before anything is built, and the New experiment form and the interactive setup
grey the benchmark out with the reason.

| Fuzzer | Also needs |
|---|---|
| aflplusplus, libafl | nothing; `rt_grammar.json` only to use a non-default runtime strategy |
| vafuzz | `rt_grammar.json` |
| configfuzz | `rt_grammar.json` |
| zigzagfuzz | `dict` |
| carpetfuzz | `carpetfuzz/combinations.txt`, `carpetfuzz/dict.json` |
| prophetfuzz | `ranked_stubs.txt` (or `prophet_argvs.txt`, used first when present) |

A benchmark without the optional files still runs with every fuzzer that does not need them.

### builder.Dockerfile

The framework builds this file for every benchmark copy, once for each fuzzer and once for coverage, with different
build arguments:

| Build | `parent_image` | Build arguments |
|---|---|---|
| fuzzing | `fbpp/fuzzer:<fuzzer>` | every `FUZZER_*` variable of the fuzzer image, such as `FUZZER_COMP` and `FUZZER_COMPXX` (the fuzzer's compilers) |
| coverage | `fbpp/base` | `CC=clang`, `CXX=clang++`, `CFLAGS=-fprofile-instr-generate -fcoverage-mapping` |

It then runs the image with a folder mounted at `/benchmark_out_dir`, and that folder becomes `/benchmark` in every
trial. So the `CMD` copies the program and every file a fuzzer or tool reads from `/benchmark`. A sample, based on
`benchmarks/xz_xz/builder.Dockerfile`. The grammar samples below are shortened from the same benchmark.

```dockerfile
ARG parent_image
FROM $parent_image

# The compilers: the fuzzer's for a fuzzing build, clang for the coverage build.
ARG CC=$FUZZER_COMP
ARG CXX=$FUZZER_COMPXX
ARG CFLAGS=""

RUN apt-get update && apt-get install -y make autoconf automake libtool

# Download a fixed version, and check it. The fallback copies it from benchmarks/sources/,
# which the framework passes as the `sources` build context, for builds without internet.
COPY --from=sources xz-5.2.5.tar.gz /fbpp_sources/
RUN ((wget --tries=3 --timeout=60 https://tukaani.org/xz/xz-5.2.5.tar.gz && \
      echo "f6f4910fd033078738bd82bfba4f49219d03b17eb0794eb91efbae419f4aba10  xz-5.2.5.tar.gz" | sha256sum -c) || \
     cp -f /fbpp_sources/xz-5.2.5.tar.gz .) && \
    tar -xzf xz-5.2.5.tar.gz

# Build in the source folder: the coverage report, the HTML source reports and SuperC use these paths.
WORKDIR /xz-5.2.5
COPY build.sh .
RUN bash build.sh

# Everything the fuzzers and tools read from /benchmark.
COPY run_target.sh build.sh rt_grammar.json dict ranked_stubs.txt manpage.1 /
COPY seed /seed
COPY carpetfuzz /carpetfuzz_analysis

# One string: the && chain runs. Copy the binary and the files above to /benchmark_out_dir.
CMD ["bash", "-c", "cp /xz-5.2.5/src/xz/xz /benchmark_out_dir/ && \
     cp /run_target.sh /build.sh /rt_grammar.json /dict /ranked_stubs.txt /manpage.1 /benchmark_out_dir/ && \
     cp -r /seed /benchmark_out_dir/seed && cp -r /carpetfuzz_analysis /benchmark_out_dir/carpetfuzz"]
```

- Pin the version (a release archive with its checksum, or a `git checkout` of a commit), so every build is the same.
- Put a copy of the archive in `benchmarks/sources/` and keep the `COPY --from=sources` fallback.
- Leave out the `COPY` of optional files the benchmark does not have.
- Build a static binary (`--disable-shared`), or copy its libraries too, so it runs from `/benchmark`.

### build.sh and run_target.sh

```bash
# build.sh: runs in the source folder. {{CT_CONFIGURATION}} is replaced by the compile-time options.
./configure --disable-shared --enable-static CC=$CC CXX=$CXX {{CT_CONFIGURATION}}
make -j$(nproc) CC=$CC CXX=$CXX
```

```bash
# run_target.sh: one line, the program in /benchmark, @@ for the input file.
/benchmark/xz -d -c @@
```

Options that `build.sh` sets itself (here `--disable-shared`) belong in `ct_grammar.json`'s `removed` list, so no
strategy changes them.

### ct_grammar.json: the compile-time options

```json
{
  "name": "xz_xz",
  "options": [
    {"name": "debug", "type": "bool", "default": false, "cli": "enable"},
    {"name": "encoders", "type": "choice", "default": "lzma1,lzma2,delta", "cli": "enable",
     "choices": ["lzma1,lzma2,delta", "lzma1,lzma2"]},
    {"name": "pic", "type": "bool", "default": true, "cli": "with"}
  ],
  "constraints": [],
  "removed": [
    {"name": "xz", "reason": "set by build.sh: xz is the benchmark target"}
  ]
}
```

- `options`: `type` is `bool` or `choice` (with `choices`). `cli` gives the flag form: `enable` gives
  `--enable-x`/`--disable-x`, `with` gives `--with-x`/`--without-x`, and a choice `--enable-x=value` or `--with-x=value`.
- `constraints`: when `opt` has `val`, every entry of `then` must hold. xz has none; libxml2's
  `{"opt": "relaxng", "val": true, "then": [{"opt": "regexps", "val": true}, {"opt": "schemas", "val": true}]}`
  says that RelaxNG needs regexps and schemas. The strategies only produce configurations that satisfy them.
- `removed`: options left out on purpose, each with its `reason`.

`./configure --help` lists the options. How the strategies use the grammar is in
[Compile-time strategies in depth](README.md#compile-time-strategies-in-depth).

### rt_grammar.json: the command-line options

```json
{
  "cmdline": "$inopts -c $INPUTFILE",
  "options": [
    {"opt": "-z", "type": "bool"},
    {"opt": "-d", "type": "bool"},
    {"opt": "-T", "type": "intnum", "range": [0, 128], "connector": " "}
  ],
  "connector": "=",
  "exit_options": ["-h", "-H", "-V"],
  "conflict": [["-z", "-d"], ["-z", "-t"]],
  "depend": [],
  "maxcombs": 3,
  "strmax": 3
}
```

- `cmdline`: the arguments after the program. `$inopts` is replaced by a configuration's options, `$INPUTFILE` by `@@`.
- `options`: `type` is `bool`, `choice` (with `choices`), `intnum` or `realnum` (with `range`: the bounds and 8 values
  between are sampled), or `string` (not sampled). `connector` joins an option and its value (`-T 4`), and the
  top-level `connector` is used for the options that do not give their own.
- `exit_options`: options with which the program exits without reading its input (help, version). They are never used.
- `conflict`: pairs of options that never appear together; `depend`: options that need others.

How the strategies use the grammar is in [Runtime strategies in depth](README.md#runtime-strategies-in-depth).

### Checking a benchmark

```bash
python3 common/run_experiment.py --config config.yaml --experiment-name xz_check \
  --fuzzers aflplusplus --benchmarks xz_xz --dry-run
```

The dry run checks the folder and the files each fuzzer needs. Then run a short experiment (one fuzzer, one or two
trials, `max_total_time: 300`) and check that the trials have coverage. The build logs are in
`<experiment>/benchmarks/<fuzzer>_<copy>_build.log`.

## Part 2: Adding a fuzzer

A fuzzer is a folder `fuzzers/<name>/`. The name is what you pass to `--fuzzers` or list in an experiment file.

### Config-agnostic or config-aware

First decide which kind your fuzzer is. The framework treats the two differently:

| | Config-agnostic | Config-aware |
|---|---|---|
| **What it fuzzes** | the input file, under the command line it is given | the input and the program's options, which it chooses itself |
| **Examples here** | aflplusplus, libafl | vafuzz, configfuzz, carpetfuzz, prophetfuzz, zigzagfuzz |
| **Runtime strategies** | yes: each strategy gives it a list of configurations, fuzzed one after another | no: it always runs with `default`, the benchmark's `run_target.sh` |
| **Compile-time strategies** | yes | yes |
| **Registered in** | `runtime/supported_fuzzers.json` | `fuzzers/benchmark_requirements.json`, for the benchmark files it reads |
| **`run.sh` must** | start from `${SEED_DIR:-/benchmark/seed}` | read the benchmark files it needs (`rt_grammar.json`, `dict`, ...) from `/benchmark` |

The interactive setup and the web app's New experiment form show the kind next to each fuzzer. The interactive setup
only asks for runtime strategies when a config-agnostic fuzzer is chosen, and the form warns when a group gives a
config-aware fuzzer a non-default runtime strategy.

### Directory layout

```
fuzzers/<name>/
├── builder.Dockerfile   builds the fuzzer image, fbpp/fuzzer:<name>
├── run.sh               fuzzes one trial
└── coverage.py          replays the trial's corpus on the coverage build and writes the coverage report
```

All three are required. Other files the fuzzer needs (patches, helper scripts) go in the same folder.

### builder.Dockerfile

```dockerfile
ARG parent_image          # the framework passes fbpp/base
FROM $parent_image

RUN apt-get update && apt-get install -y build-essential git
# A fixed commit, so every build is the same.
RUN git clone https://github.com/<you>/<fuzzer> /<name> && \
    cd /<name> && git checkout <commit> && make

# The compilers the benchmarks are built with: every FUZZER_* variable is passed to the
# benchmark builds as a build argument, and benchmarks use these two as CC and CXX.
ENV FUZZER_COMP=/<name>/afl-clang-fast
ENV FUZZER_COMPXX=/<name>/afl-clang-fast++

COPY run.sh coverage.py /<name>/
# The framework runs the image once with <experiment>/fuzzers mounted at /fuzzer_output.
# This copies /<name> there; in every trial that folder is /fuzzer.
CMD ["bash", "-c", "cp -r /<name> /fuzzer_output/"]
```

Put `run.sh` and `coverage.py` inside `/<name>`: only that folder reaches the trials.

### run.sh

`run.sh` runs in the `fbpp/runner` image, pinned to two CPUs, with the memory limit from `config.yaml`. It gets:

| Given | Value |
|---|---|
| `/fuzzer` | the folder your image copied out |
| `/benchmark` | the benchmark built with your compiler, with `run_target.sh`, `seed/` and the optional files |
| `$OUT` | the trial's output folder: write everything here |
| `$RUNTIME` | seconds to fuzz; `0` in [continuous mode](README.md#continuous-mode), meaning no limit |
| `$RUN_TARGET` | the command to fuzz, from `run_target.sh` (under a runtime strategy, with the configuration's options) |
| `$SEED_DIR` | under a runtime strategy: the seeds to start from (the previous configuration's corpus) |

A **config-agnostic** fuzzer fuzzes `$RUN_TARGET` as given, and takes its seeds from `$SEED_DIR` (from
`fuzzers/aflplusplus/run.sh`):

```bash
# A time limit when RUNTIME > 0; none when it is 0 or unset (continuous mode).
LIMIT=""; [ "${RUNTIME:-0}" -gt 0 ] 2>/dev/null && LIMIT="-V $RUNTIME"
export AFL_IGNORE_SEED_PROBLEMS=1
/fuzzer/afl-fuzz -i ${SEED_DIR:-/benchmark/seed} -o $OUT $LIMIT $RUN_TARGET
```

A **config-aware** fuzzer reads the benchmark's option files and chooses the options itself (from
`fuzzers/zigzagfuzz/run.sh`, which mutates the options with the benchmark's `dict`):

```bash
LIMIT=""; [ "${RUNTIME:-0}" -gt 0 ] 2>/dev/null && LIMIT="-V $RUNTIME"
/fuzzer/afl-fuzz -i /benchmark/seed -o $OUT -K 2 -a /benchmark/dict $LIMIT $RUN_TARGET
```

Both must:

- stop after `$RUNTIME` seconds, or run until stopped when it is `0`. The container is killed after `$RUNTIME + 600`
  seconds, and the trial counts as failed;
- write the corpus to `$OUT/default/queue/` and crashes to `$OUT/default/crashes/` (AFL++'s layout), which
  `coverage.py` and [crash triage](crash-triage.md) read;
- for a config-aware fuzzer, save the command line of each input and crash (as `default/queue_argvs/` and
  `default/crashes_argvs/` in VAFuzz and ZigZagFuzz), so that coverage and triage can replay it with the same options.

### coverage.py

`coverage.py` runs after fuzzing in `fbpp/runner-coverage`, with `/benchmark` now the coverage build of the same
benchmark copy, `/fuzzer_output` the trial's folder, and `$OUT` and `$RUN_TARGET` as above. It must:

1. run `$RUN_TARGET` on every input of the corpus (with `@@` replaced by the input's path, or the input on stdin),
   with `LLVM_PROFILE_FILE` set and a timeout;
2. merge the profiles: `llvm-profdata merge -sparse --failure-mode=warn -f inputs.txt -o $OUT/coverage/merged.profdata`,
   with the profiles in a file list, one `1,<path>` per line (a large queue exceeds the argument limit, and the weight
   keeps the commas in AFL's queue names apart);
3. write `$OUT/coverage/report.json` with `llvm-cov export <binary> -instr-profile=... -format=lcov` and
   `$OUT/coverage/report.txt` with `llvm-cov report <binary> -instr-profile=...`. The binary is the first word of
   `$RUN_TARGET`.

Start from `fuzzers/aflplusplus/coverage.py`, which does exactly this. A config-aware fuzzer must replay each input
with the options it was found with: see `fuzzers/vafuzz/coverage.py` and `fuzzers/zigzagfuzz/coverage.py`. In
continuous mode, `coverage.py` is run on part of the queue at a time, so it must work on any subset of it.

### Registering it

A **config-agnostic** fuzzer is added to `runtime/supported_fuzzers.json`, with the folder (relative to `$OUT`) where
it writes its corpus. That folder is passed on as `$SEED_DIR` to the next configuration:

```json
{
  "aflplusplus": {"corpus_dir": "default/queue"},
  "libafl": {"corpus_dir": "default/queue"},
  "<name>": {"corpus_dir": "default/queue"}
}
```

With that entry, and a `run.sh` that reads `${SEED_DIR:-/benchmark/seed}`, every runtime strategy works with it.
Under a runtime strategy, `runtime/multi_config_run.sh` calls your `run.sh` once per configuration, with `$OUT` set to
`$OUT/config_<i>`, `$RUNTIME` to that configuration's share of the time and `$RUN_TARGET` to the program with the
configuration's options. `runtime/multi_config_coverage.sh` then calls your `coverage.py` once per configuration, so
neither needs to know about runtime strategies.

A **config-aware** fuzzer stays out of `supported_fuzzers.json`. If it needs benchmark files beyond the required ones,
list them in `fuzzers/benchmark_requirements.json` (paths relative to `benchmarks/<benchmark>/`):

```json
{
  "vafuzz": ["rt_grammar.json"],
  "zigzagfuzz": ["dict"],
  "<name>": ["rt_grammar.json"]
}
```

Optionally, add a one-line description to `FUZZER_DESCRIPTIONS` in `common/interactive.py`, which the interactive
setup shows next to the fuzzer.

### Checking a fuzzer

```bash
python3 common/run_experiment.py --config config.yaml --experiment-name myfuzzer_check \
  --fuzzers <name> --benchmarks xz_xz --dry-run
```

Then run a short experiment and look at:

- the fuzzer image's build: `<experiment>/fuzzers/<name>_build.log`;
- a trial's fuzzing and coverage: `<experiment>/data/<trial>/<fuzzer>_<copy>_trial<k>.log`;
- the coverage: `coverage/report.txt` should end with a `TOTAL` row with covered regions, lines and branches;
- for a config-agnostic fuzzer, the same with `--runtime-strategy random`: `rt_run.jsonl` and `config_<i>/` in the
  trial's folder.

The framework does not rebuild an image that exists: after changing your fuzzer, remove it with
`docker rmi fbpp/fuzzer:<name>`.

## Before you open a pull request

- Run the tests: `python3 -m pytest tests` (see [Tests](README.md#tests)).
- Run `--dry-run` and one short experiment with the new benchmark or fuzzer, as above.
- Do not commit `config.yaml`, experiment files, results or the `benchmarks/cts_*` copies.
- Add the new benchmark or fuzzer to the tables of this guide.

## See also

- [Strategies in depth](README.md#strategies-in-depth): how compile-time and runtime strategies use the grammars.
- [Coverage reports](coverage-reports.md): what is done with `report.json` and `report.txt`.
- The web app's [Documentation page](web-app.md#documentation-page): the plugin interfaces, also for crash triage
  and post-analysis tools.
