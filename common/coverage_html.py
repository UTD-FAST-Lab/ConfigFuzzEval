"""Combined coverage reports of every arm's trials, for the statistics report: the union and
the mean, both written every time.

Union (FuzzBench's coverage reports): the arm's trial profiles are merged and llvm-cov show
writes a browsable report to <statistics>/html/<benchmark>/<arm>/index.html, with what any
trial covered. Profiles merge only on one binary, so for an arm whose trials ran on several
benchmark copies (or without profiles) the union is made from the trials' LCOV reports
instead, in the same layout as the mean report (union_files.csv).

Mean: from the trials' LCOV reports, <statistics>/html/mean/<benchmark>/<arm>/index.html gives
per file the mean (and standard deviation) over the trials of the lines, branches and functions
they covered, and per source line how many of the trials covered it and its mean execution
count; mean_files.csv has the per-file numbers. Unlike the union, it shows what a typical trial
reaches, and how reliably each line is reached.

Only the source files the coverage build uses are copied out of its Docker image, into
<statistics>/html/src/<copy>/. <statistics>/html/index.html links every report.
"""
import csv
import html
import json
import math
import os
import shlex
import shutil
import subprocess
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

from color_logger import get_logger

logging = get_logger(__name__)

# One source copy per benchmark copy at a time, as several arms share it.
_source_locks = defaultdict(threading.Lock)


def coverage_binary(experiment_path, cts_benchmark):
    """The coverage binary of a benchmark copy, from the first word of its run_target.sh
    (a path under /benchmark, where the coverage container mounts the folder)."""
    build_dir = os.path.join(experiment_path, "benchmarks", f"coverage_{cts_benchmark}")
    with open(os.path.join(build_dir, "run_target.sh"), encoding="utf-8") as f:
        target = shlex.split(f.read())[0]
    return os.path.join(build_dir, os.path.relpath(target, "/benchmark"))


def trial_profile(trial_dir):
    path = os.path.join(trial_dir, "coverage", "merged.profdata")
    return path if os.path.isfile(path) and os.path.getsize(path) > 0 else None


# --- HTML source reports (FuzzBench's CoverageReporter.generate_coverage_report) ---

def source_files(binary, profdata):
    """Source files the coverage mapping of |binary| refers to."""
    result = subprocess.run(["llvm-cov", "export", "-summary-only", binary, f"-instr-profile={profdata}"],
                            check=True, capture_output=True, text=True)
    export = json.loads(result.stdout.strip().splitlines()[-1])
    return sorted({f["filename"] for unit in export["data"] for f in unit["files"]})


def copy_sources(cts_benchmark, filenames, src_root):
    """Copies |filenames| (absolute paths in the build) out of the coverage image of
    |cts_benchmark| into |src_root|, keeping their paths, once. The coverage build has
    the sources where it was compiled. Returns False if it cannot."""
    marker = os.path.join(src_root, ".copied")
    if os.path.isfile(marker):
        return True
    image = f"fbpp/benchmark:coverage_{cts_benchmark}"
    os.makedirs(src_root, exist_ok=True)
    names = "\n".join(name.lstrip("/") for name in filenames if name.startswith("/")) + "\n"
    packer = subprocess.Popen(["docker", "run", "--rm", "-i", "--entrypoint", "tar", image,
                               "-C", "/", "--ignore-failed-read", "-cf", "-", "-T", "-"],
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    unpacker = subprocess.Popen(["tar", "-x", "-C", src_root], stdin=packer.stdout,
                                stderr=subprocess.PIPE)
    packer.stdout.close()
    packer.stdin.write(names.encode())
    packer.stdin.close()
    unpack_error = unpacker.communicate()[1]
    pack_error = packer.stderr.read()
    packer.wait()
    # tar exits 1 when a listed file is missing (a generated file of the build, say),
    # which --ignore-failed-read reports but does not stop.
    if packer.returncode not in (0, 1) or unpacker.returncode != 0:
        logging.warning(f"Cannot copy the sources of {cts_benchmark} from {image}: "
                        f"{(pack_error + unpack_error).decode(errors='replace').strip()[-500:]}")
        return False
    open(marker, "w").close()
    return True


def html_report(experiment_path, out_dir, benchmark, arm, trials):
    """html/<benchmark>/<arm>/index.html from the arm's merged trial profiles, or None.

    Profiles can only be merged on one binary, so an arm whose trials ran on several
    benchmark copies (a compile-time strategy with many configurations) is skipped.
    """
    copies = {c for t in trials for c in t["cts_benchmarks"]}
    if len(copies) != 1:
        logging.info(f"Union report of {arm} on {benchmark} from the LCOV reports: its trials ran on "
                     f"{len(copies)} benchmark copies, whose profiles llvm-cov cannot merge")
        return None
    cts_benchmark = copies.pop()
    profiles = [p for t in trials for p in map(trial_profile, t["dirs"]) if p]
    if not profiles:
        return None
    report_dir = os.path.join(out_dir, "html", benchmark, arm)
    shutil.rmtree(report_dir, ignore_errors=True)
    os.makedirs(report_dir)
    merged = os.path.join(report_dir, "merged.profdata")
    try:
        binary = coverage_binary(experiment_path, cts_benchmark)
        subprocess.run(["llvm-profdata", "merge", "-sparse", *profiles, "-o", merged],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        src_root = os.path.join(out_dir, "html", "src", cts_benchmark)
        with _source_locks[src_root]:
            copy_sources(cts_benchmark, source_files(binary, merged), src_root)
    except (OSError, IndexError, subprocess.CalledProcessError) as e:
        logging.warning(f"No HTML report for {arm} on {benchmark}: {e}")
        return None
    result = subprocess.run(
        ["llvm-cov", "show", "-format=html", f"-path-equivalence=/,{src_root}", f"-output-dir={report_dir}",
         "-Xdemangler", "c++filt", "-Xdemangler", "-n", binary, f"-instr-profile={merged}"],
        capture_output=True, text=True)
    if result.returncode != 0:
        logging.warning(f"HTML report for {arm} on {benchmark} failed: {result.stderr.strip()[-500:]}")
        return None
    return os.path.join(report_dir, "index.html")


# --- Mean over the trials, from their LCOV reports ---

def lcov_counts(path):
    """{file: {"lines": {line: count}, "branches": {(line, block, branch): taken},
    "functions": {name: count}}} of an LCOV report (llvm-cov export -format=lcov)."""
    files = {}
    current = None
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            tag, _, value = line.rstrip("\n").partition(":")
            if tag == "SF":
                current = files.setdefault(value, {"lines": {}, "branches": {}, "functions": {}})
            elif current is None:
                continue
            elif tag == "DA":
                parts = value.split(",")
                if len(parts) >= 2:
                    count = int(parts[1]) if parts[1].lstrip("-").isdigit() else 0
                    current["lines"][int(parts[0])] = current["lines"].get(int(parts[0]), 0) + max(count, 0)
            elif tag == "BRDA":
                parts = value.split(",")
                if len(parts) == 4:
                    key = tuple(parts[:3])
                    taken = int(parts[3]) if parts[3].isdigit() else 0
                    current["branches"][key] = current["branches"].get(key, 0) + taken
            elif tag == "FNDA":
                count, _, name = value.partition(",")
                current["functions"][name] = current["functions"].get(name, 0) + (int(count) if count.isdigit() else 0)
            elif tag == "FN":
                current["functions"].setdefault(value.partition(",")[2], 0)
    return files


def trial_counts(trial):
    """lcov_counts of a trial, its benchmark copies added together, or None without a report."""
    merged = {}
    for trial_dir in trial["dirs"]:
        path = os.path.join(trial_dir, "coverage", "report.json")
        if not os.path.isfile(path):
            continue
        for source, kinds in lcov_counts(path).items():
            into = merged.setdefault(source, {"lines": {}, "branches": {}, "functions": {}})
            for kind, counts in kinds.items():
                for key, n in counts.items():
                    into[kind][key] = into[kind].get(key, 0) + n
    return merged or None


def mean_sd(values):
    values = list(values)
    if not values:
        return float("nan"), float("nan")
    mean = sum(values) / len(values)
    sd = math.sqrt(sum((v - mean) ** 2 for v in values) / (len(values) - 1)) if len(values) > 1 else 0.0
    return mean, sd


def combine_mean(per_trial):
    """Per file, from [lcov_counts of each trial]: the instrumented lines, branches and functions
    (of any trial), per trial how many it covered and how many any trial covered (the union); per
    line the trials that covered it and its mean execution count."""
    n = len(per_trial)
    files = {}
    for source in sorted({s for counts in per_trial for s in counts}):
        entry = {"trials": n}
        for kind in ("lines", "branches", "functions"):
            keys = set().union(*(counts.get(source, {}).get(kind, {}).keys() for counts in per_trial))
            entry[kind] = len(keys)
            entry[f"{kind}_covered"] = [sum(1 for v in counts.get(source, {}).get(kind, {}).values() if v > 0)
                                        for counts in per_trial]
            entry[f"{kind}_union"] = len({k for counts in per_trial
                                          for k, v in counts.get(source, {}).get(kind, {}).items() if v > 0})
        lines = {}
        for counts in per_trial:
            for number, count in counts.get(source, {}).get("lines", {}).items():
                hit, total = lines.get(number, (0, 0))
                lines[number] = (hit + (count > 0), total + count)
        entry["line_hits"] = {number: (hit, total / n) for number, (hit, total) in lines.items()}
        files[source] = entry
    return files


CSS = """body{font:13px system-ui,sans-serif;margin:20px;color:#222}table{border-collapse:collapse}
td,th{border:1px solid #ddd;padding:3px 8px;text-align:right}th{background:#f4f4f4}td:first-child,th:first-child{text-align:left}
.src td{border:none;padding:0 8px;font:12px ui-monospace,monospace;white-space:pre;text-align:right}.src td.code{text-align:left}
.all{background:#d9f2d9}.some{background:#fff1c2}.none{background:#f8d4d4}.muted{color:#777}a{color:#0b57d0}
@media (prefers-color-scheme:dark){body{background:#1b1b1b;color:#ddd}th{background:#2a2a2a}td,th{border-color:#333}a{color:#8ab4f8}
.all{background:#1f3d23}.some{background:#4a3f17}.none{background:#4a1f1f}.muted{color:#999}}"""


def _line_class(hit, n):
    return "all" if hit == n else "some" if hit else "none"


def _fmt_mean(mean, sd, total):
    if total == 0 or math.isnan(mean):
        return "–"
    return f"{mean:,.1f} ± {sd:,.1f} / {total:,} ({mean / total * 100:.1f}%)"


def _fmt_union(covered, total):
    return "–" if total == 0 else f"{covered:,} / {total:,} ({covered / total * 100:.1f}%)"


def lcov_report(experiment_path, out_dir, benchmark, arm, trials, method="mean"):
    """The arm's trials combined from their LCOV reports, or None without any.

    mean:  html/mean/<benchmark>/<arm>/, the coverage averaged over the trials (mean_files.csv);
    union: html/<benchmark>/<arm>/, what any trial covered (union_files.csv), where llvm-cov's
           union report cannot be made (no profiles, or trials on several benchmark copies).
    Both show per source line the trials that covered it and its mean (or, for the union, total)
    execution count."""
    per_trial = [c for c in map(trial_counts, trials) if c]
    if not per_trial:
        return None
    n = len(per_trial)
    mean = method == "mean"
    files = combine_mean(per_trial)
    report_dir = os.path.join(out_dir, "html", *(("mean",) if mean else ()), benchmark, arm)
    shutil.rmtree(report_dir, ignore_errors=True)
    os.makedirs(os.path.join(report_dir, "files"))
    cts_benchmark = trials[0]["cts_benchmarks"][0]
    src_root = os.path.join(out_dir, "html", "src", cts_benchmark)
    try:
        with _source_locks[src_root]:
            have_sources = copy_sources(cts_benchmark, list(files), src_root)
    except OSError as error:                  # no Docker: the report without the source text
        logging.warning(f"No sources for the {method} report of {arm} on {benchmark}: {error}")
        have_sources = False
    e = html.escape
    kinds = ("lines", "branches", "functions")

    with open(os.path.join(report_dir, f"{method}_files.csv"), "w", newline="") as f:
        writer = csv.writer(f)
        if mean:
            writer.writerow(["file", "trials", "lines", "lines_covered_mean", "lines_covered_sd", "branches",
                             "branches_covered_mean", "branches_covered_sd", "functions", "functions_covered_mean",
                             "functions_covered_sd", "lines_covered_by_every_trial", "lines_covered_by_some_trial"])
        else:
            writer.writerow(["file", "trials", "lines", "lines_covered", "branches", "branches_covered", "functions",
                             "functions_covered", "lines_covered_by_every_trial"])
        for source, s in files.items():
            hits = [h for h, _ in s["line_hits"].values()]
            every = sum(1 for h in hits if h == n)
            if mean:
                writer.writerow([source, n, s["lines"], *mean_sd(s["lines_covered"]), s["branches"],
                                 *mean_sd(s["branches_covered"]), s["functions"], *mean_sd(s["functions_covered"]),
                                 every, sum(1 for h in hits if h)])
            else:
                writer.writerow([source, n] + [x for k in kinds for x in (s[k], s[f"{k}_union"])] + [every])

    rows = []
    for i, (source, s) in enumerate(files.items()):
        page = f"files/{i:04d}.html"
        cells = (_fmt_mean(*mean_sd(s[f"{k}_covered"]), s[k]) if mean else _fmt_union(s[f"{k}_union"], s[k])
                 for k in kinds)
        rows.append(f"<tr><td><a href='{page}'>{e(source)}</a></td>" + "".join(f"<td>{c}</td>" for c in cells)
                    + f"<td>{sum(1 for h, _ in s['line_hits'].values() if h == n):,}</td>"
                    + f"<td>{sum(1 for h, _ in s['line_hits'].values() if 0 < h < n):,}</td></tr>")
        text = []
        path = os.path.join(src_root, source.lstrip("/"))
        if have_sources and os.path.isfile(path):
            with open(path, encoding="utf-8", errors="replace") as src:
                text = src.read().split("\n")
        last = max([len(text), *s["line_hits"]])
        body = []
        for number in range(1, last + 1):
            hit = s["line_hits"].get(number)
            code = e(text[number - 1]) if number <= len(text) else ""
            if hit is None:
                body.append(f"<tr><td class='muted'>{number}</td><td></td><td></td><td class='code'>{code}</td></tr>")
            else:
                count = hit[1] if mean else hit[1] * n
                body.append(f"<tr class='{_line_class(hit[0], n)}'><td>{number}</td><td>{hit[0]}/{n}</td>"
                            f"<td>{count:,.{1 if mean else 0}f}</td><td class='code'>{code}</td></tr>")
        with open(os.path.join(report_dir, page), "w", encoding="utf-8") as out:
            out.write(f"<!doctype html><meta charset='utf-8'><title>{e(os.path.basename(source))} ({method})</title>"
                      f"<style>{CSS}</style><p><a href='../index.html'>&larr; {e(arm)} on {e(benchmark)}</a></p>"
                      f"<h2>{e(source)}</h2><p>{'Mean over' if mean else 'Union of'} {n} trial(s). Per line: the trials "
                      f"that covered it and its {'mean' if mean else 'total'} execution count. Green: every trial; "
                      f"yellow: some; red: none."
                      + ("" if text else " <i>The source is not available, so only line numbers are shown.</i>")
                      + f"</p><table class='src'><tr><th>Line</th><th>Trials</th><th>{'Mean' if mean else 'Total'} count</th>"
                      f"<th></th></tr>" + "\n".join(body) + "</table>")

    totals = []
    if mean:
        for metric in ("regions", "functions", "lines", "branches"):
            values = [t["values"][metric] for t in trials if metric in t["values"]]
            instrumented = max((t["instrumented"].get(metric, 0) for t in trials), default=0)
            if values:
                mean_value, sd = mean_sd(values)
                totals.append(f"<tr><td>{metric}</td><td>{_fmt_mean(mean_value, sd, instrumented)}</td>"
                              f"<td>{min(values):,}</td><td>{max(values):,}</td></tr>")
        head = "<th>Metric</th><th>Covered (mean ± sd / instrumented)</th><th>Worst trial</th><th>Best trial</th>"
    else:
        for metric in kinds:
            totals.append(f"<tr><td>{metric}</td><td>{_fmt_union(sum(s[f'{metric}_union'] for s in files.values()), sum(s[metric] for s in files.values()))}</td></tr>")
        head = "<th>Metric</th><th>Covered by any trial / instrumented</th>"
    every = sum(1 for s in files.values() for h, _ in s["line_hits"].values() if h == n)
    some = sum(1 for s in files.values() for h, _ in s["line_hits"].values() if h)
    intro = (f"Coverage averaged over the trials (mean ± standard deviation / instrumented). The union report shows "
             f"what any trial covered; this one what a typical trial covers." if mean else
             f"What any of the trials covered, from their LCOV reports (llvm-cov's own union report needs the "
             f"trials' profiles on one benchmark copy, which this arm does not have). The mean report shows what a "
             f"typical trial covers.")
    with open(os.path.join(report_dir, "index.html"), "w", encoding="utf-8") as out:
        out.write(f"<!doctype html><meta charset='utf-8'><title>{e(arm)} on {e(benchmark)} ({method})</title><style>{CSS}</style>"
                  f"<h1>{e(arm)} on {e(benchmark)}: {method} of {n} trial(s)</h1>"
                  f"<p>{intro} Lines covered by every trial: {every:,}; by at least one (the union): {some:,}.</p>"
                  f"<table><tr>{head}</tr>{''.join(totals)}</table><h2>Files</h2>"
                  f"<table><tr><th>File</th><th>Lines</th><th>Branches</th><th>Functions</th>"
                  f"<th>Lines in every trial</th><th>Lines in some trials</th></tr>{''.join(rows)}</table>"
                  f"<p>Per file: <a href='{method}_files.csv'>{method}_files.csv</a>.</p>")
    return os.path.join(report_dir, "index.html")


def mean_report(experiment_path, out_dir, benchmark, arm, trials):
    """html/mean/<benchmark>/<arm>/index.html, the arm's coverage averaged over its trials, or None."""
    return lcov_report(experiment_path, out_dir, benchmark, arm, trials, "mean")


def union_report(experiment_path, out_dir, benchmark, arm, trials):
    """html/<benchmark>/<arm>/index.html: llvm-cov's report of the merged profiles, or, where there is none
    (no profiles, or trials on several benchmark copies), the union of the trials' LCOV reports."""
    return (html_report(experiment_path, out_dir, benchmark, arm, trials)
            or lcov_report(experiment_path, out_dir, benchmark, arm, trials, "union"))


def write_index(out_dir, reports):
    """html/index.html: the union and mean report of every benchmark and arm."""
    e = html.escape
    keys = sorted({(b, a) for _, b, a in reports})
    rows = "".join(f"<tr><td>{e(b)}</td><td>{e(a)}</td>" + "".join(
        f"<td><a href='{e(os.path.relpath(reports[(m, b, a)], os.path.join(out_dir, 'html')))}'>{m}</a></td>"
        if (m, b, a) in reports else "<td class='muted'>–</td>" for m in ("union", "mean")) + "</tr>" for b, a in keys)
    with open(os.path.join(out_dir, "html", "index.html"), "w", encoding="utf-8") as f:
        f.write(f"<!doctype html><meta charset='utf-8'><title>Combined coverage reports</title><style>{CSS}</style>"
                f"<h1>Combined coverage reports</h1><p>Every arm's trials combined: <b>union</b> (what any trial "
                f"covered: llvm-cov's source view of the merged profiles, or, for an arm whose trials ran on several "
                f"benchmark copies, the union of their LCOV reports) and <b>mean</b> (the average over the trials, "
                f"and per line how many trials covered it).</p>"
                f"<table><tr><th>Benchmark</th><th>Arm</th><th>Union</th><th>Mean</th></tr>{rows}</table>")


def html_reports(res, out_dir, jobs=None):
    """The union and mean report of every arm and benchmark; {(method, benchmark, arm): index.html}."""
    groups = defaultdict(list)
    for t in res["trials"]:
        groups[(t["benchmark"], t["arm"])].append(t)
    tasks = [(method, *key) for key in groups for method in ("union", "mean")]
    build = {"union": union_report, "mean": mean_report}

    def run(task):
        method, benchmark, arm = task
        try:
            return build[method](res["experiment_path"], out_dir, benchmark, arm, groups[(benchmark, arm)])
        except (OSError, ValueError) as e:
            logging.warning(f"No {method} report for {arm} on {benchmark}: {e}")
            return None
    with ThreadPoolExecutor(max_workers=jobs or min(4, os.cpu_count() or 1)) as pool:
        reports = {task: path for task, path in zip(tasks, pool.map(run, tasks)) if path}
    if reports:
        write_index(out_dir, reports)
    return reports
