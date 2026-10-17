"""The SuperC presence-condition report, read for the web app's Presence conditions tab.

common/superc.py writes <report>/superc/pc_summary.csv (one row per benchmark build and
arm), <report>/superc/<benchmark>[_cts_<cts>]_pc_comparison.csv (every condition, with
each arm's covered lines) and, per benchmark build, <experiment>/superc/<copy>/status.tsv
(SuperC's exit code and time per file). This only reads them.
"""
import csv
import os

INT_FIELDS = ("trials", "files", "files_analysed", "conditions", "conditions_in_build",
              "conditions_covered_union", "conditional_lines_in_build", "conditional_lines_covered_union",
              "covered_lines_union", "covered_lines_in_headers", "covered_lines_without_condition")
TIMEOUT_CODES = (124, 137)        # timeout(1), and SIGKILL after it


def report_dir(config, name):
    return os.path.join(config["report_filestore"], name, "superc")


def has_report(config, name):
    return os.path.isfile(os.path.join(report_dir(config, name), "pc_summary.csv"))


def comparison_key(benchmark, cts):
    """The comparison file's name stem, as superc.write_report names it."""
    return benchmark if cts == "default" else f"{benchmark}_cts_{cts}"


def _number(value):
    try:
        f = float(value)
    except (TypeError, ValueError):
        return 0
    return int(f) if f.is_integer() else f


def _comparison_rows(path):
    with open(path, newline="") as f:
        reader = csv.reader(f)
        header = next(reader, [])
        arms = [h.split(":", 1)[1] for h in header[4:] if h.startswith("covered_lines:")]
        rows = []
        for r in reader:
            if len(r) < 4 + len(arms):
                continue
            rows.append({"condition": r[0], "instrumented": _number(r[1]),
                         "covered_by": [a for a in r[2].split(";") if a],
                         "only": r[3] or None,
                         "lines": {a: _number(v) for a, v in zip(arms, r[4:4 + len(arms)])}})
    return arms, rows


def _build_status(experiment_path, benchmark, cts):
    """SuperC's per-file results for the benchmark build (copy 0), or None if not found."""
    path = os.path.join(experiment_path, "superc", f"cts_{cts}_{benchmark}_0", "status.tsv")
    if not os.path.isfile(path):
        return None
    status = {}
    with open(path, newline="") as f:
        for row in csv.reader(f, delimiter="\t"):
            if len(row) == 3:
                try:
                    status[row[0]] = (int(row[1]), int(row[2]))
                except ValueError:
                    continue
    problems = sorted(([p, c, s] for p, (c, s) in status.items() if c != 0), key=lambda x: x[0])
    return {"files": len(status), "ok": sum(1 for c, _ in status.values() if c == 0),
            "timed_out": sum(1 for c, _ in status.values() if c in TIMEOUT_CODES),
            "failed": sum(1 for c, _ in status.values() if c not in (0,) + TIMEOUT_CODES),
            "seconds": sum(s for _, s in status.values()),
            "problems": [{"file": p, "code": c, "seconds": s,
                          "reason": "timed out" if c in TIMEOUT_CODES else f"exit code {c}"} for p, c, s in problems]}


def overview(config, name):
    """Every benchmark build of the report: its arms' rows, the conditions only each arm
    covered, how many conditions no arm covered, and SuperC's per-file results."""
    rdir = report_dir(config, name)
    summary = os.path.join(rdir, "pc_summary.csv")
    if not os.path.isfile(summary):
        return None
    builds = {}
    with open(summary, newline="") as f:
        for row in csv.DictReader(f):
            row = {k: (_number(v) if k in INT_FIELDS or k == "conditions_covered_median_trial" else v)
                   for k, v in row.items()}
            key = comparison_key(row["benchmark"], row["compiletime"])
            b = builds.setdefault(key, {"key": key, "benchmark": row["benchmark"], "compiletime": row["compiletime"],
                                        "arms": [], "rows": []})
            b["arms"].append(row["arm"])
            b["rows"].append(row)
    experiment_path = os.path.join(config["experiment_filestore"], name)
    for b in builds.values():
        comparison = os.path.join(rdir, f"{b['key']}_pc_comparison.csv")
        b["comparison_file"] = os.path.basename(comparison) if os.path.isfile(comparison) else None
        only, uncovered, in_build = {a: 0 for a in b["arms"]}, 0, 0
        if b["comparison_file"]:
            _, rows = _comparison_rows(comparison)
            for r in rows:
                if r["instrumented"]:
                    in_build += 1
                    if not r["covered_by"]:
                        uncovered += 1
                if r["only"] in only:
                    only[r["only"]] += 1
        b["only"] = only
        b["uncovered"] = uncovered
        b["in_build"] = in_build or max((r["conditions_in_build"] for r in b["rows"]), default=0)
        b["superc"] = _build_status(experiment_path, b["benchmark"], b["compiletime"])
    return {"builds": sorted(builds.values(), key=lambda b: (b["benchmark"], b["compiletime"] != "default",
                                                              b["compiletime"])),
            "files": sorted(f for f in os.listdir(rdir) if f.endswith((".csv", ".html")))}


SORTS = {
    "instrumented": lambda r, arm: (-r["instrumented"], r["condition"]),
    "condition": lambda r, arm: (r["condition"],),
    "arm": lambda r, arm: (-r["lines"].get(arm, 0), -r["instrumented"], r["condition"]),
    "missed": lambda r, arm: (-(r["instrumented"] - max(r["lines"].values(), default=0)), r["condition"]),
}


def conditions(config, name, key, show="all", arm=None, query="", sort="instrumented", offset=0, limit=100):
    """The conditions of one benchmark build, filtered, sorted and paged.

    show: "all", "in_build" (the build instrumented a line under it), "covered" (some arm
    covered it), "uncovered" (in the build, no arm covered it), "only" (only |arm| covered
    it) or "missed" (another arm covered it, |arm| did not)."""
    path = os.path.join(report_dir(config, name), f"{key}_pc_comparison.csv")
    if not os.path.isfile(path):
        return None
    arms, rows = _comparison_rows(path)
    if arm not in arms:
        arm = None
    q = (query or "").strip().lower()
    keep = {
        "all": lambda r: True,
        "in_build": lambda r: r["instrumented"] > 0,
        "covered": lambda r: bool(r["covered_by"]),
        "uncovered": lambda r: r["instrumented"] > 0 and not r["covered_by"],
        "only": lambda r: arm is not None and r["only"] == arm,
        "missed": lambda r: arm is not None and r["covered_by"] and arm not in r["covered_by"],
    }.get(show, lambda r: True)
    selected = [r for r in rows if keep(r) and (not q or q in r["condition"].lower())]
    selected.sort(key=lambda r: SORTS.get(sort, SORTS["instrumented"])(r, arm or (arms[0] if arms else None)))
    offset, limit = max(0, offset), max(1, min(limit, 1000))
    return {"arms": arms, "total": len(rows), "matching": len(selected), "offset": offset,
            "rows": selected[offset:offset + limit]}
