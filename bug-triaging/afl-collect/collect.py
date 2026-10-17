#!/usr/bin/env python3
"""Crash triage of one trial with afl-collect (afl-utils), with each crash's own command line.

Run by common/docker_image_builder.run_triaging in fbpp/bug-triaging:afl-collect, with the
mounts and variables of crash_commands.py, /triaging_output (pooled over the trials of one
fuzzer, runtime strategy and benchmark copy) and OWNER (uid:gid, who gets the results).

For every crash folder of the trial (default/crashes, or config_<i>/default/crashes for a
runtime strategy), afl-collect collects the crashes into collection/, keeps those that crash
again (-r) and classifies them with gdb and exploitable (-e) into crashes.db (table Data:
Sample, Classification, Classification_Description, Hash = exploitable's
"<major hash>.<minor hash>", User_Comment). Its target is launcher.py, which runs each crash
with the command line it was found with. A bug is a distinct major hash (the top frames of
the stack), as afl-collect's classification groups crashes.
"""
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crash_commands import FUZZER, RESULTS, TRIAL, crash_dirs  # noqa: E402

LAUNCHER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "launcher.py")


def main():
    RESULTS.mkdir(parents=True, exist_ok=True)
    database = RESULTS / "crashes.db"
    crashes = 0
    for config, fuzzer_dir, run_target in crash_dirs():
        crash_dir = fuzzer_dir / "crashes"
        samples = sorted(p for p in crash_dir.iterdir() if p.is_file() and p.name.startswith("id")) \
            if crash_dir.is_dir() else []
        if not samples:
            continue
        crashes += len(samples)
        # afl-collect reads <sync dir>/<fuzzer instance>/crashes/ and names its copies
        # "<instance>:<crash>"; the instance names the trial and configuration.
        instance = f"trial_{TRIAL}" + (f"_{config}" if config else "")
        sync = Path(tempfile.mkdtemp(prefix="sync_"))
        (sync / instance / "crashes").mkdir(parents=True)
        for sample in samples:
            shutil.copyfile(sample, sync / instance / "crashes" / sample.name)
        env = dict(os.environ, LAUNCH_FUZZER_DIR=str(fuzzer_dir), LAUNCH_RUN_TARGET=run_target,
                   LLVM_PROFILE_FILE="/dev/null")
        collection = RESULTS / "collection" / instance
        shutil.rmtree(collection, ignore_errors=True)
        print(f"[afl-collect] {len(samples)} crash(es) of {instance}", flush=True)
        subprocess.run(["afl-collect", "-d", str(database), "-e", "gdb_script", "-r",
                        "-j", str(max(1, len(os.sched_getaffinity(0)))), str(sync), str(collection),
                        "--", sys.executable, LAUNCHER, "@@"], env=env, check=False)
        shutil.rmtree(sync, ignore_errors=True)
    bugs = set()
    if database.is_file():
        db = sqlite3.connect(database)
        bugs = {r[0].split(".")[0] for r in db.execute("SELECT Hash FROM Data WHERE Hash IS NOT NULL AND Hash != ''")}
        db.close()
    print(f"[afl-collect] {FUZZER} trial {TRIAL}: {crashes} crash(es); {len(bugs)} distinct bug(s) "
          f"(exploitable major hash) so far over the pooled trials")
    if os.environ.get("OWNER"):
        subprocess.run(["chown", "-R", os.environ["OWNER"], str(RESULTS)], check=False)


if __name__ == "__main__":
    main()
