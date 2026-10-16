"""Progress events of an experiment, one JSON object per line in <experiment>/events.jsonl.

The web app (webapp/) reads them to show an experiment's phase and the state of each
trial; the log stays the place for details. Every event has "time" (Unix seconds) and
"event": "phase" (with "phase"), "trial_start" / "trial_end" (with the trial and, for
trial_end, "status") or "finished".
"""
import json
import os
import threading
import time

_lock = threading.Lock()


def emit(experiment_path, event, **fields):
    """Appends one event; never raises, so progress reporting cannot break an experiment."""
    if not experiment_path:
        return
    record = {"time": round(time.time(), 3), "event": event, **fields}
    try:
        with _lock, open(os.path.join(experiment_path, "events.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except OSError:
        pass


def read(experiment_path):
    """Every event of an experiment, oldest first ([] without an events file)."""
    path = os.path.join(experiment_path, "events.jsonl")
    if not os.path.isfile(path):
        return []
    out = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out
