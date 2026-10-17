"""Reading experiments from the filestore: their state, phase, trials and reports.

Everything comes from what common/run_experiment.py writes (experiment_state.pkl,
events.jsonl, data/<trial>/...), so experiments started from the command line show up
the same as those started from the web app.
"""
import os
import pickle
import re
import time

import events
from statistical_analysis import parse_report_txt

ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
CTS = re.compile(r"^cts_([^_]+)_(.+)_(\d+)$")
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def run_label(fuzzer, rts):
    return fuzzer if rts == "default" else f"{fuzzer}_rts_{rts}"


def valid_name(name):
    return bool(NAME.match(name or "")) and ".." not in name


def load_state(experiment_path):
    path = os.path.join(experiment_path, "experiment_state.pkl")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "rb") as f:
            return pickle.load(f)
    except Exception:
        return None


def list_experiments(config):
    root = config["experiment_filestore"]
    if not os.path.isdir(root):
        return []
    out = []
    for e in os.scandir(root):
        if e.is_dir() and valid_name(e.name):
            out.append({"name": e.name, "path": e.path, "mtime": e.stat().st_mtime})
    return sorted(out, key=lambda x: -x["mtime"])


def statistics_path(config, name):
    path = os.path.join(config["report_filestore"], name, "statistics", "index.html")
    return path if os.path.isfile(path) else None


def summary(config, name, running_names=()):
    """Phase, status and trial counts of one experiment, cheap enough for the list page."""
    path = os.path.join(config["experiment_filestore"], name)
    evs = events.read(path)
    state = load_state(path)
    planned = len(state.get("trial_tasks", [])) if state else None
    done = sum(1 for e in evs if e["event"] == "trial_end")
    failed = sum(1 for e in evs if e["event"] == "trial_end" and e.get("status") != "success")
    phases = [e for e in evs if e["event"] == "phase"]
    finished = any(e["event"] == "finished" for e in evs)
    running = name in running_names
    if not evs:
        # Experiments from before events.jsonl: count the trials' coverage reports
        data = os.path.join(path, "data")
        done = sum(1 for t in (os.listdir(data) if os.path.isdir(data) else [])
                   if os.path.isfile(os.path.join(data, t, "coverage", "report.txt")))
    if running:
        status = "running"
    elif finished:
        status = "finished"
    elif evs:
        status = "stopped"
    else:
        status = "finished" if planned and done >= planned else ("incomplete" if state else "unknown")
    started = evs[0]["time"] if evs else (os.path.getmtime(os.path.join(path, "experiment_state.pkl"))
                                          if state else None)
    ended = evs[-1]["time"] if evs and finished else None
    return {"name": name, "status": status, "phase": phases[-1]["phase"] if phases else None,
            "planned": planned, "done": done, "failed": failed, "started": started, "ended": ended,
            "has_stats": statistics_path(config, name) is not None,
            "has_superc": os.path.isfile(os.path.join(config["report_filestore"], name, "superc", "pc_summary.csv")),
            "fuzzers": state.get("fuzzers", []) if state else [],
            "benchmarks": state.get("benchmarks", []) if state else [],
            "runtime_strategies": state.get("runtime_strategies", []) if state else []}


def trials(config, name, running=False):
    """Every planned trial with its state, core and final coverage."""
    path = os.path.join(config["experiment_filestore"], name)
    state = load_state(path)
    if not state:
        return []
    evs = events.read(path)
    started, ended = {}, {}
    for e in evs:
        if e["event"] in ("trial_start", "trial_end"):
            key = (e["run"], e["benchmark"], int(e["trial"]))
            (started if e["event"] == "trial_start" else ended)[key] = e
    out = []
    for fuzzer, rts, benchmark, trial, *_ in state.get("trial_tasks", []):
        label = run_label(fuzzer, rts)
        key = (label, benchmark, int(trial))
        trial_dir_name = f"{label}_{benchmark}_trial_{trial}"
        trial_dir = os.path.join(path, "data", trial_dir_name)
        report = os.path.join(trial_dir, "coverage", "report.txt")
        totals = parse_report_txt(report) if os.path.isfile(report) else None
        if key in ended:
            status = ended[key].get("status", "success")
        elif key in started:
            status = "running" if running else "interrupted"
        elif totals:
            status = "success"
        elif os.path.isdir(trial_dir):
            status = "running" if running else "failure"
        else:
            status = "queued" if running else "not run"
        start = started.get(key, {}).get("time")
        end = ended.get(key, {}).get("time")
        pc = f"data/{trial_dir_name}/pc_analysis/pc_coverage_summary.csv"
        log = f"data/{trial_dir_name}/{label}_{benchmark}_trial{trial}.log"
        m = CTS.match(benchmark)
        out.append({"run": label, "arm": fuzzer if rts == "default" else f"{fuzzer}[{rts}]",
                    "bench": m.group(2) if m else benchmark, "cts": m.group(1) if m else "default",
                    "copy": int(m.group(3)) if m else 0,
                    "fuzzer": fuzzer, "rts": rts, "benchmark": benchmark, "trial": trial,
                    "status": status, "core": started.get(key, {}).get("core"),
                    "seconds": (end or time.time()) - start if start else None,
                    "branches": totals.get("branches") if totals else None,
                    "lines": totals.get("lines") if totals else None,
                    "log": log if os.path.isfile(os.path.join(path, log)) else None,
                    "pc": pc if os.path.isfile(os.path.join(path, pc)) else None})
    return out


def tail(path, max_bytes=200_000):
    """The end of a text file, without colour codes."""
    if not path or not os.path.isfile(path):
        return ""
    with open(path, "rb") as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - max_bytes))
        data = f.read().decode("utf-8", errors="replace")
    if size > max_bytes:
        data = data[data.find("\n") + 1:]
    return ANSI.sub("", data)
