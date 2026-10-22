#!/usr/bin/env python3
"""afl-collect's target: runs the program on one crash with the crash's own command line.

afl-collect replays every crash of a folder with one command, written into a gdb script and
run through a shell: fuzzed arguments (bytes that are not text, spaces, empty arguments) do
not survive that, and every @@ becomes the crash file. So afl-collect is given the plain
command "launcher.py @@": this looks the crash up (crash_commands.py, as the fuzzer's
coverage.py does) and replaces itself with the program and its exact arguments (execve).
gdb follows the exec, so afl-collect and exploitable see the program's crash.

Environment (set by collect.py): LAUNCH_FUZZER_DIR, the fuzzer's output folder of the crash
(default/ or config_<i>/default/); LAUNCH_RUN_TARGET, that folder's run target; and the
variables crash_commands.py reads (FUZZER_NAME, the mounts).
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crash_commands import commands  # noqa: E402


def crash_name(sample_name):
    """The fuzzer's crash name of afl-collect's copy "<fuzzer instance>:<crash name>"."""
    if not sample_name.startswith("id") and ":" in sample_name:
        return sample_name.split(":", 1)[1]
    return sample_name


def main():
    sample = Path(sys.argv[1])
    name = crash_name(sample.name)
    scratch = Path(tempfile.mkdtemp(prefix="launch_"))   # options may write next to the input
    work_input = scratch / "input"
    shutil.copyfile(sample, work_input)
    tries = commands(name, work_input, Path(os.environ["LAUNCH_FUZZER_DIR"]), os.environ["LAUNCH_RUN_TARGET"], scratch)
    if not tries:
        sys.exit(0)          # no command line (a ConfigFuzz input that does not decode): no crash
    # The first command (VAFuzz: the first configuration the input crashed under)
    argv, stdin = tries[0]
    os.chdir(scratch)
    if stdin:
        fd = os.open(stdin, os.O_RDONLY)
        os.dup2(fd, 0)
    argv = [a if isinstance(a, bytes) else os.fsencode(a) for a in argv]
    os.execv(argv[0], argv)


if __name__ == "__main__":
    main()
