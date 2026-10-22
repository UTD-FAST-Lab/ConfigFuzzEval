"""Which command line each crash of a trial needs, shared by the triagers in bug-triaging/
(gdb-exploitable/triage.py and afl-collect/launcher.py), as each fuzzer's coverage.py replays
its inputs. Copied into each triager's image next to its script.

The trial's folders are the triagers' mounts:
  /fuzzer_output   the trial (read-only): default/crashes, or config_<i>/default/crashes for a
                   runtime strategy (rt_run.jsonl, rt_configs.json)
  /benchmark       the trial's coverage build (read-only), with run_target.sh
  /fuzzer          the fuzzer's folder of the experiment (read-only)
  FUZZER_NAME      the fuzzer

The command line of a crash depends on the fuzzer:
  aflplusplus, libafl (and unknown fuzzers): the benchmark's run_target.sh
  zigzagfuzz:  default/crashes_argvs/id:<N>, the full argv the target ran with
  carpetfuzz, prophetfuzz: the "argv:<N>" in the crash name, a line of the ranked commands
  vafuzz:      default/crashes_argvs/id:<N>_<k>, the configurations it crashed under
  configfuzz:  the options encoded in the input, decoded by ConfigFuzz's printer
A runtime-strategy trial's crashes run with the configuration they were found under. Arguments
are bytes or str: they go to the program as given (execve), never through a shell.
"""
import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path

# The mounts; TRIAGE_OUT, TRIAGE_RESULTS and TRIAGE_BENCHMARK move them (for tests).
OUT = Path(os.environ.get("TRIAGE_OUT", "/fuzzer_output"))
RESULTS = Path(os.environ.get("TRIAGE_RESULTS", "/triaging_output"))
BENCHMARK = Path(os.environ.get("TRIAGE_BENCHMARK", "/benchmark"))
FUZZER = os.environ.get("FUZZER_NAME", "")
TRIAL = os.environ.get("TRIAL", "0")
RUN_TARGET = (BENCHMARK / "run_target.sh").read_text().strip() if (BENCHMARK / "run_target.sh").is_file() else ""
BINARY = shlex.split(RUN_TARGET)[0] if RUN_TARGET else ""

# ZigZagFuzz's __afl_change_argv limits (as fuzzers/zigzagfuzz/coverage.py)
MAX_CMDLINE_LEN, MAX_CMDLINE_PAR = 100000, 50000


# --- Crash folders and their command lines -------------------------------------------

def crash_dirs():
    """[(configuration label, the fuzzer's output folder, run target)] of the trial."""
    run_log = OUT / "rt_run.jsonl"
    if not run_log.is_file():
        return [("", OUT / "default", RUN_TARGET)]
    configs = json.loads((OUT / "rt_configs.json").read_text())["configs"]
    out = []
    for line in run_log.read_text().splitlines():
        if line.strip():
            i = json.loads(line)["config"]
            # As runtime/multi_config_run.sh: the binary and the configuration's arguments.
            out.append((f"config_{i}", OUT / f"config_{i}" / "default", " ".join([BINARY] + configs[i])))
    return out


def plain(run_target, crash):
    """The run target, with the crash as its @@ file or on stdin."""
    args = shlex.split(run_target)
    if "@@" in args:
        return [[a if a != "@@" else str(crash) for a in args], None]
    return [args, crash]


def zigzag_argv(raw, crash):
    raw = raw.replace(b"@@", os.fsencode(crash), 1)[:MAX_CMDLINE_LEN - 2]
    args = []
    for word in raw.split(b"\x00"):
        if not word or len(args) >= MAX_CMDLINE_PAR - 1:
            break
        args.append(b"" if word == b"\x02" else word)
    return args


def ranked_commands():
    """CarpetFuzz/ProphetFuzz: the commands afl-fuzz numbers argv:0, argv:1, ..."""
    for path in (OUT / "ranked_stubs.txt", BENCHMARK / "prophet_argvs.txt", BENCHMARK / "ranked_stubs.txt"):
        if path.is_file():
            lines = [line.strip() for line in path.read_text().splitlines()]
            return [line for line in lines[1:int(lines[0]) + 1] if line]
    return []


_printer = None


def configfuzz_printer():
    """ConfigFuzz's printer for this benchmark (as fuzzers/configfuzz/coverage.py)."""
    global _printer
    if _printer is None:
        grammar = Path(BINARY).parent / "rt_grammar.json"
        work = Path(tempfile.mkdtemp(prefix="configfuzz_"))
        with open(work / "printer.c", "w") as f:
            subprocess.run(["python3", "/fuzzer/make_stub.py", "printer", str(grammar)], stdout=f, check=True)
        subprocess.run(["clang", "-O2", "-w", "-o", str(work / "printer"), str(work / "printer.c"), "-lm"], check=True)
        uses_stdin = "$STDIN" in json.loads(grammar.read_text())["cmdline"]
        _printer = (str(work / "printer"), uses_stdin)
    return _printer


def commands(name, crash, fuzzer_dir, run_target, scratch):
    """[(argv, stdin file or None)] to try for one crash, in order: the first that crashes counts."""
    crash_id = name.split(",")[0]
    if FUZZER == "zigzagfuzz":
        argv_file = fuzzer_dir / "crashes_argvs" / crash_id
        if argv_file.is_file():
            return [[[BINARY] + zigzag_argv(argv_file.read_bytes(), crash), None]]
    elif FUZZER in ("carpetfuzz", "prophetfuzz"):
        match = re.search(r"argv:(\d+)", name)
        lines = ranked_commands()
        n = int(match.group(1)) if match else 0
        if n < len(lines):
            parts = shlex.split(lines[n])
            return [[[BINARY] + [str(crash) if p == "@@" else p for p in parts[1:]], None]]
    elif FUZZER == "vafuzz":
        configs = sorted((fuzzer_dir / "crashes_argvs").glob(f"{crash_id}_*")) \
            if (fuzzer_dir / "crashes_argvs").is_dir() else []
        out = []
        program, *args = shlex.split(run_target)
        for config_file in configs:
            options = [t for t in config_file.read_text(errors="replace").strip().split(" ") if t]
            if "@@" in args:
                out.append([[program] + options + [str(crash) if a == "@@" else a for a in args], None])
            else:
                out.append([[program] + options + args, crash])
        if out:
            return out
    elif FUZZER == "configfuzz":
        printer, uses_stdin = configfuzz_printer()
        for f in Path("/dev/shm").glob("optfuzzer.*"):
            f.unlink()
        decoded = subprocess.run([printer, str(crash)], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        args = decoded.stdout.decode(errors="surrogateescape").splitlines()
        data = next(Path("/dev/shm").glob("optfuzzer.*"), None)
        if decoded.returncode == 0 and args:
            kept = None
            if data is not None:          # keep the data part: the next decode removes it
                kept = scratch / "configfuzz_data"
                shutil.copyfile(data, kept)
                args = [str(kept) if a == str(data) else a for a in args]
            return [[[BINARY] + args[1:], kept if uses_stdin else None]]
        return []                          # options that do not decode: no command line
    return [plain(run_target, crash)]


def printable(argv):
    """A command line for people: bytes that are not UTF-8 become \\x.. escapes."""
    words = [a if isinstance(a, bytes) else os.fsencode(a) for a in argv]
    return " ".join(shlex.quote(w.decode("utf-8", "backslashreplace")) for w in words)
