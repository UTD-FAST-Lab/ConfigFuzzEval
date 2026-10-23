"""The Crash triage tab: an experiment's triage results in one place.

Reads bug-triaging/<triager>/output/<pooled>/ of an experiment, as the triage tools write it
(see docs/crash-triage.md): pool.json (the run and benchmark copy the folder pools the trials
of), crashes.db (table Data: one row per crash, Hash = the bug key, empty when the crash did not
crash again), trial_<k>.log, and for gdb-exploitable bugs/<key>/ (crash_state.txt, command.txt,
gdb.txt). Bugs are counted as the statistics report's Found bugs counts them
(statistical_analysis.found_bugs): a distinct Hash up to its first ".", per arm and benchmark,
with the copies of a compile-time strategy combined.
"""
import json
import os
import sqlite3

MAX_BUGS = 2000          # bugs listed in the answer; the counts always include every bug


def _rows(db):
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        cols = {r[1] for r in con.execute("PRAGMA table_info(Data)")}
        desc = "Classification_Description" if "Classification_Description" in cols else "''"
        rows = con.execute(f"SELECT Sample, Classification, {desc}, Hash FROM Data").fetchall()
        con.close()
        return rows
    except sqlite3.Error:
        return None


def _read(path, limit=4000):
    try:
        with open(path, errors="replace") as f:
            return f.read(limit).strip()
    except OSError:
        return None


def summary(experiment_path):
    """{ok, triagers, arms, benchmarks, counts, tasks, bugs} for the Crash triage tab.

    counts: {triager: {benchmark: {arm: distinct bugs, "union": over all arms}}}
    tasks:  one per triager and pooled folder: its run, copy, trials, crashes, reproduced, bugs, logs
    bugs:   one per triager, benchmark and bug key: the arms (with their crash counts) and copies
            that found it, its classification and, when the triager saved them, its crash state and
            the command line it was replayed with.
    """
    from statistical_analysis import CTS_BENCHMARK, arm_name
    root = os.path.join(experiment_path, "bug-triaging")
    out = {"ok": False, "triagers": [], "arms": [], "benchmarks": [], "counts": {}, "tasks": [], "bugs": []}
    if not os.path.isdir(root):
        return out
    arms, benchmarks, bugs = set(), set(), {}
    for triager in sorted(os.listdir(root)):
        output = os.path.join(root, triager, "output")
        if not os.path.isdir(output):
            continue
        out["triagers"].append(triager)
        counts = out["counts"].setdefault(triager, {})
        for pooled in sorted(os.listdir(output)):
            folder = os.path.join(output, pooled)
            try:
                with open(os.path.join(folder, "pool.json")) as f:
                    info = json.load(f)
            except (OSError, ValueError):
                continue
            m = CTS_BENCHMARK.match(info.get("benchmark", ""))
            cts, bench = (m.group("cts"), m.group("benchmark")) if m else ("default", info.get("benchmark", pooled))
            rts = info.get("runtime_strategy", "default")
            arm = arm_name(info.get("fuzzer", "?"), rts, cts)
            arms.add(arm)
            benchmarks.add(bench)
            rel = os.path.relpath(folder, experiment_path)
            logs = sorted((f for f in os.listdir(folder) if f.startswith("trial_") and f.endswith(".log")),
                          key=lambda f: int("".join(c for c in f if c.isdigit()) or 0))
            rows = _rows(os.path.join(folder, "crashes.db")) if os.path.isfile(os.path.join(folder, "crashes.db")) else []
            keys = set()
            for sample, classification, description, hash_ in rows or []:
                if not hash_:
                    continue
                key = hash_.split(".")[0]
                keys.add(key)
                bug = bugs.setdefault((triager, bench, key), {
                    "triager": triager, "benchmark": bench, "key": key, "classification": classification,
                    "description": description, "arms": {}, "copies": [], "crashes": 0, "state": None,
                    "command": None, "folder": None, "files": []})
                bug["crashes"] += 1
                bug["arms"][arm] = bug["arms"].get(arm, 0) + 1
                if info.get("benchmark") not in bug["copies"]:
                    bug["copies"].append(info.get("benchmark"))
                saved = os.path.join(folder, "bugs", key)
                if bug["folder"] is None and os.path.isdir(saved):
                    bug["folder"] = os.path.relpath(saved, experiment_path)
                    bug["state"] = _read(os.path.join(saved, "crash_state.txt"))
                    bug["command"] = _read(os.path.join(saved, "command.txt"))
                    bug["files"] = [f for f in ("crash_state.txt", "command.txt", "gdb.txt") if os.path.isfile(os.path.join(saved, f))]
            per_bench = counts.setdefault(bench, {})
            per_bench.setdefault(arm, set()).update(keys)
            per_bench.setdefault("union", set()).update(keys)
            out["tasks"].append({
                "triager": triager, "folder": rel, "run": pooled.split("_cts_")[0], "arm": arm, "benchmark": bench,
                "copy": info.get("benchmark"), "cts": cts, "rts": rts, "trials": info.get("trials") or [],
                "crashes": len(rows) if rows is not None else None,
                "reproduced": sum(1 for r in rows if r[3]) if rows is not None else None,
                "bugs": len(keys), "logs": [os.path.join(rel, f) for f in logs],
                "database": os.path.isfile(os.path.join(folder, "crashes.db"))})
    for triager, per in out["counts"].items():
        for bench, by_arm in per.items():
            per[bench] = {a: len(s) for a, s in by_arm.items()}
    order = lambda a: ("{cts:" in a, a.split("{")[0].split("[")[0], a)
    out["arms"] = sorted(arms, key=order)
    out["benchmarks"] = sorted(benchmarks)
    listed = sorted(bugs.values(), key=lambda b: (b["triager"], b["benchmark"], -len(b["arms"]), -b["crashes"], b["key"]))
    out["bugs_total"] = len(listed)
    out["bugs"] = listed[:MAX_BUGS]
    out["ok"] = bool(out["tasks"])
    return out
