"""The Live tab: every trial with the fuzzer's own statistics, read from its running container.

A trial's folder is mounted at /fuzzer_output, where AFL++ (and the fuzzers built on it) keep
fuzzer_stats, plot_data and crashes/. The folder is root's, so the files are read through the
container: one `docker exec` per running trial, found by the fbpp.experiment label every
experiment container carries. A finished trial is read the same way from a throwaway container.
"""
import json
import os
import re
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import events
import experiments as exps

FOLDER = re.compile(r"^[A-Za-z0-9_.+-]+$")
CARD_POINTS = 60        # plot_data rows per trial card
DETAIL_POINTS = 400     # rows in the trial detail window
CACHE_SECONDS = 3
SERIES = ("execs_per_sec", "corpus_count", "edges_found", "saved_crashes")

# Prints the newest fuzzer_stats under /fuzzer_output (a runtime strategy has one per
# configuration), plot_data thinned to about $1 rows, the crash files and the processes.
PROBE = r"""
echo "@now $(date +%s)"
f=$(ls -t $(find /fuzzer_output -maxdepth 3 -name fuzzer_stats 2>/dev/null) 2>/dev/null | head -n 1)
if [ -n "$f" ]; then
  d=$(dirname "$f")
  echo "@dir $d"
  echo "@mtime $(stat -c %Y "$f")"
  echo "@stats"; cat "$f"
  if [ -f "$d/plot_data" ]; then
    n=$(wc -l < "$d/plot_data"); k=$(( n / $1 + 1 ))
    echo "@plot"; awk -v k="$k" -v n="$n" 'NR == 1 || (NR - 2) % k == 0 || NR == n' "$d/plot_data"
  fi
  echo "@crashes"; ls "$d/crashes" 2>/dev/null | grep -v '^README' | tail -n 200
fi
echo "@ps"; ps -eo args=
"""

_cache = {}
_lock = threading.Lock()


def docker(*args, timeout=20):
    try:
        r = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout)
        return r.stdout if r.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def containers(name):
    """{trial folder: [container, ...]} of the experiment's running containers."""
    ids = (docker("ps", "-q", "--filter", f"label=fbpp.experiment={name}") or "").split()
    if not ids:
        return {}
    out = {}
    for c in json.loads(docker("inspect", *ids) or "[]"):
        for m in c.get("Mounts", []):
            if m.get("Destination") == "/fuzzer_output":
                out.setdefault(os.path.basename(os.path.normpath(m["Source"])), []).append(c["Name"].lstrip("/"))
    return out


def number(v):
    v = v.strip().rstrip("%")
    try:
        return float(v) if "." in v else int(v)
    except ValueError:
        return None


def parse_probe(text):
    """The sections PROBE prints: now, mtime, raw fuzzer_stats, plot_data rows, crashes, processes."""
    out = {"stats": {}, "plot": [], "crashes": [], "ps": []}
    section = None
    for line in (text or "").splitlines():
        if line.startswith("@now ") or line.startswith("@mtime "):
            key, _, v = line.partition(" ")
            out[key[1:]] = number(v)
        elif line.startswith("@dir "):
            out["dir"] = line[5:]
        elif line in ("@stats", "@plot", "@crashes", "@ps"):
            section = line[1:]
        elif section == "stats":
            k, sep, v = line.partition(":")
            if sep:
                out["stats"][k.strip()] = v.strip()
        elif section and line.strip():
            out[section].append(line.strip())
    return out


def series(plot_rows, points=None):
    """plot_data as {t: [seconds], execs_per_sec: [...], ...}, from its header line."""
    if not plot_rows or not plot_rows[0].startswith("#"):
        return {}
    cols = [c.strip() for c in plot_rows[0].lstrip("#").split(",")]
    rows = [[number(v) for v in r.split(",")] for r in plot_rows[1:]]
    rows = [r for r in rows if len(r) == len(cols)]
    if points and len(rows) > points:
        step = len(rows) / points
        rows = [rows[int(i * step)] for i in range(points - 1)] + [rows[-1]]
    col = {c: i for i, c in enumerate(cols)}
    if "relative_time" in col:
        t = [r[col["relative_time"]] for r in rows]
    elif "unix_time" in col and rows:            # older AFL: absolute times
        t = [r[col["unix_time"]] - rows[0][col["unix_time"]] for r in rows]
    else:
        return {}
    out = {"t": t}
    for k in SERIES:
        if k in col:
            out[k] = [r[col[k]] for r in rows]
    if "edges_found" not in out and "map_size" in col:
        out["map_size"] = [r[col["map_size"]] for r in rows]
    return out


def summary(probe):
    """The numbers of a trial card, from fuzzer_stats."""
    s = probe["stats"]
    if not s:
        return None
    n = {k: number(v) for k, v in s.items()}
    # last_find and last_crash are on AFL++'s own clock, like last_update; the file was
    # written at mtime, on the container's clock, like now.
    stale = (probe.get("now") or 0) - (probe.get("mtime") or 0) if probe.get("mtime") else 0

    def ago(key):
        if not n.get(key) or n.get("last_update") is None:
            return None
        return max(0, n["last_update"] - n[key] + max(0, stale))

    eps = n.get("execs_ps_last_min") or n.get("execs_per_sec")
    return {"run_time": n.get("run_time"), "execs_per_sec": eps, "execs_done": n.get("execs_done"),
            "corpus_count": n.get("corpus_count"), "corpus_favored": n.get("corpus_favored"),
            "pending_total": n.get("pending_total"), "pending_favs": n.get("pending_favs"),
            "cycles_done": n.get("cycles_done"), "saved_crashes": n.get("saved_crashes"),
            "saved_hangs": n.get("saved_hangs"), "bitmap_cvg": n.get("bitmap_cvg"),
            "edges_found": n.get("edges_found"), "total_edges": n.get("total_edges"),
            "stability": n.get("stability"), "last_find_ago": ago("last_find"),
            "last_crash_ago": ago("last_crash"), "max_depth": n.get("max_depth"),
            "command_line": s.get("command_line"), "fuzzer_version": s.get("afl_version")}


def stage(probe):
    """fuzzing, or coverage when the container replays the corpus (the fuzzing time is over)."""
    ps = " ".join(probe["ps"])
    if "afl-fuzz" in ps:
        return "fuzzing"
    if any(k in ps for k in ("coverage.py", "multi_config_coverage", "llvm-profdata", "llvm-cov")):
        return "coverage"
    return "fuzzing"


def probe_container(container, points):
    return parse_probe(docker("exec", container, "sh", "-c", PROBE, "probe", str(points), timeout=15))


def probe_trial(name, folders, points):
    """{folder: probe} of the running trials, a fuzzing container preferred over a coverage one."""
    out = {}
    jobs = [(f, c) for f, cs in folders.items() for c in cs]
    with ThreadPoolExecutor(max_workers=min(16, len(jobs) or 1)) as pool:
        for (folder, _), p in zip(jobs, pool.map(lambda j: probe_container(j[1], points), jobs)):
            if folder not in out or (stage(p) == "fuzzing" and p["stats"] and stage(out[folder]) != "fuzzing"):
                out[folder] = p
    return out


def planned_seconds(state):
    """{(run, benchmark, trial): fuzzing seconds} of an evaluation; none in continuous mode."""
    if (state or {}).get("mode") == "continuous":
        return {}
    out = {}
    for fuzzer, rts, benchmark, trial, tot_cts, _, max_total_time, *_ in state.get("trial_tasks", []):
        if max_total_time:
            out[(exps.run_label(fuzzer, rts), benchmark, int(trial))] = max_total_time / max(1, tot_cts or 1)
    return out


def build_logs(path):
    """The experiment's build and triage logs, relative to its folder."""
    out = []
    for sub, group in (("fuzzers", "build"), ("benchmarks", "build"), ("bug-triaging", "triage")):
        root = os.path.join(path, sub)
        if not os.path.isdir(root):
            continue
        for dirpath, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if group == "triage" or dirpath == root]
            for f in sorted(files):
                if f.endswith(".log"):
                    out.append({"group": group, "path": os.path.relpath(os.path.join(dirpath, f), path)})
    return out


def overview(config, name, running):
    """What the Live tab shows: every trial, the running ones with their statistics and charts."""
    key = (name, running)
    with _lock:
        hit = _cache.get(key)
        if hit and hit[0] > time.time() - CACHE_SECONDS:
            return hit[1]
    path = os.path.join(config["experiment_filestore"], name)
    state = exps.load_state(path)
    trials = exps.trials(config, name, running)
    planned = planned_seconds(state) if state else {}
    probes = probe_trial(name, containers(name), CARD_POINTS) if running else {}
    totals = {"execs_per_sec": 0, "execs_done": 0, "saved_crashes": 0, "saved_hangs": 0, "fuzzing": 0}
    for t in trials:
        t["folder"] = f"{t['run']}_{t['benchmark']}_trial_{t['trial']}"
        t["planned"] = planned.get((t["run"], t["benchmark"], int(t["trial"])))
        p = probes.get(t["folder"])
        if t["status"] != "running":
            continue
        t["stage"] = stage(p) if p else "fuzzing"
        t["stats"] = summary(p) if p else None
        t["series"] = series(p["plot"]) if p else {}
        if t["stats"] and t["stage"] == "fuzzing":
            totals["fuzzing"] += 1
            for k in ("execs_per_sec", "execs_done", "saved_crashes", "saved_hangs"):
                totals[k] += t["stats"].get(k) or 0
    data = {"now": time.time(), "running": running, "trials": trials, "totals": totals,
            "phases": [e for e in events.read(path) if e["event"] == "phase"],
            "triage": None, "triagers": (state or {}).get("built_triagers") or [], "superc": None,
            "logs": build_logs(path) if os.path.isdir(path) else []}
    with _lock:
        _cache[key] = (time.time(), data)
    return data


def tail(path, max_bytes=30_000):
    return exps.tail(path, max_bytes)


def trial(config, name, folder, running):
    """One trial's full fuzzer_stats, charts, crash files and logs; None if there is no such trial."""
    if not FOLDER.match(folder or "") or ".." in folder:
        return None
    path = os.path.join(config["experiment_filestore"], name)
    trial_dir = os.path.join(path, "data", folder)
    if not os.path.isdir(trial_dir):
        return None
    cs = containers(name).get(folder, []) if running else []
    if cs:
        probe, source = probe_trial(name, {folder: cs}, DETAIL_POINTS)[folder], "live"
    else:
        # A finished trial: its files are root's, so read them through a throwaway container.
        out = docker("run", "--rm", "--network", "none", "-v", f"{trial_dir}:/fuzzer_output:ro",
                     "--entrypoint", "sh", "fbpp/runner", "-c", PROBE, "probe", str(DETAIL_POINTS), timeout=60)
        probe, source = parse_probe(out), "files"
    logs = {f: tail(os.path.join(trial_dir, f)) for f in sorted(os.listdir(trial_dir)) if f.endswith(".log")}
    return {"ok": True, "source": source, "folder": folder, "summary": summary(probe),
            "stats": probe["stats"], "series": series(probe["plot"]), "configs": [],
            "crashes": probe["crashes"], "logs": logs}
