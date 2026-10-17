"""Statistical analysis of an experiment's final coverage, written as an HTML report.

Reads every trial's coverage/report.txt (llvm-cov report: covered and instrumented
regions, functions, lines and branches) and coverage/report.json (LCOV: the covered
lines and branches themselves, for unique coverage, Jaccard and UpSet), and compares
the experiment's arms: one arm is a fuzzer under a runtime strategy (and compile-time
strategy, when not default), shown as "fuzzer[strategy]" like the other reports.

The statistics follow FuzzBench (Metzman et al., FSE 2021) where it has them:
medians, two-sided Mann-Whitney U with Vargha-Delaney A12, Holm correction,
Kruskal-Wallis with Dunn's post-hoc test, the one-sided "better than" matrix,
Friedman with a Nemenyi critical-difference diagram, average rank, average
normalized score, unique coverage rankings, relative coverage, first places, the
low-sample flag and found bugs; plus the minimum achievable p-value, Jaccard
similarity, UpSet intersections, trial variability and the union of a runtime
strategy's configurations against its best single one.

Usage (or through post_analysis.py --stats):
    python3 common/statistical_analysis.py EXPERIMENT_PATH [-o OUT_DIR] [--compare-to OTHER_EXPERIMENT_PATH]
"""
import argparse
import html
import io
import itertools
import json
import math
import os
import re
import sqlite3
from collections import Counter, defaultdict

import numpy as np
from scipy import stats

from color_logger import get_logger
import coverage_html

logging = get_logger(__name__)

METRICS = ("branches", "lines", "regions", "functions")
ALPHA = 0.05
LOW_SAMPLE_FRACTION = 0.8
CTS_BENCHMARK = re.compile(r"^cts_(?P<cts>[^_]+)_(?P<benchmark>.+)_(?P<bin_no>\d+)$")
TRIAL_DIR = re.compile(r"^(?P<label>.+)_(?P<benchmark>cts_.+_\d+)_trial_(?P<trial>\d+)$")


# ---------------------------------------------------------------------------
# Loading trials
# ---------------------------------------------------------------------------

def parse_report_txt(path):
    """{metric: (covered, instrumented)} from the TOTAL row of an llvm-cov report.

    The row is: regions, missed regions, cover, functions, missed functions,
    executed, lines, missed lines, cover, branches, missed branches, cover.
    """
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        total = next((l.split() for l in f if l.startswith("TOTAL")), None)
    if total is None:
        return None
    values = total[1:]
    out = {}
    for metric, (count_i, missed_i) in zip(("regions", "functions", "lines", "branches"),
                                           ((0, 1), (3, 4), (6, 7), (9, 10))):
        try:
            count, missed = int(values[count_i]), int(values[missed_i])
        except (IndexError, ValueError):
            continue
        out[metric] = (count - missed, count)
    return out


def parse_lcov_sets(path):
    """(covered lines, covered branches) of an LCOV report, as sets of
    (file, line) and (file, line, block, branch)."""
    lines, branches = set(), set()
    filename = None
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.startswith("SF:"):
                filename = line[3:].rstrip("\n")
            elif line.startswith("DA:"):
                parts = line[3:].rstrip("\n").split(",")
                if len(parts) >= 2 and parts[1] not in ("0", "-"):
                    lines.add((filename, int(parts[0])))
            elif line.startswith("BRDA:"):
                parts = line[5:].rstrip("\n").split(",")
                if len(parts) == 4 and parts[3] not in ("0", "-"):
                    branches.add((filename, int(parts[0]), parts[1], parts[2]))
    return lines, branches


def trial_identity(entry, trial_dir):
    """fuzzer, runtime strategy, compile-time strategy, benchmark, copy and trial of a trial directory."""
    info_path = os.path.join(trial_dir, "trial_info.json")
    if os.path.isfile(info_path):
        with open(info_path, "r", encoding="utf-8") as f:
            info = json.load(f)
        fuzzer, rts, cts_benchmark, trial = info["fuzzer"], info.get("runtime_strategy", "default"), \
            info["benchmark"], int(info["trial"])
    else:
        # Trials from before trial_info.json: <fuzzer>[_rts_<strategy>]_cts_<cts>_<benchmark>_<copy>_trial_<n>
        match = TRIAL_DIR.match(entry)
        if not match:
            return None
        label, cts_benchmark, trial = match.group("label"), match.group("benchmark"), int(match.group("trial"))
        fuzzer, _, rts = label.partition("_rts_")
        rts = rts or "default"
    match = CTS_BENCHMARK.match(cts_benchmark)
    cts, benchmark, copy = (match.group("cts"), match.group("benchmark"), int(match.group("bin_no"))) \
        if match else ("default", cts_benchmark, 0)
    return {"fuzzer": fuzzer, "rts": rts, "cts": cts, "benchmark": benchmark, "copy": copy, "trial": trial}


def arm_name(fuzzer, rts, cts):
    name = fuzzer if rts == "default" else f"{fuzzer}[{rts}]"
    return name if cts == "default" else f"{name}{{cts:{cts}}}"


def load_trials(experiment_path):
    """One record per (arm, benchmark, trial).

    A trial whose compile-time strategy built several copies of the benchmark ran on
    every copy, with the fuzzing time split between them; its copies are combined by
    the union of their covered lines and branches (regions and functions cannot be
    combined from the reports and are left out for such trials).
    """
    data_dir = os.path.join(experiment_path, "data")
    copies = defaultdict(list)
    for entry in sorted(os.listdir(data_dir)):
        trial_dir = os.path.join(data_dir, entry)
        if not os.path.isdir(trial_dir):
            continue
        ident = trial_identity(entry, trial_dir)
        if ident is None:
            continue
        report_txt = os.path.join(trial_dir, "coverage", "report.txt")
        report_lcov = os.path.join(trial_dir, "coverage", "report.json")
        if not (os.path.isfile(report_txt) and os.path.isfile(report_lcov)):
            logging.warning(f"No coverage report in {trial_dir}, trial left out")
            continue
        totals = parse_report_txt(report_txt)
        if not totals:
            logging.warning(f"No TOTAL row in {report_txt}, trial left out")
            continue
        lines, branches = parse_lcov_sets(report_lcov)
        copies[(ident["fuzzer"], ident["rts"], ident["cts"], ident["benchmark"], ident["trial"])].append(
            {"dir": trial_dir, "totals": totals, "lines": lines, "branches": branches,
             "cts_benchmark": f"cts_{ident['cts']}_{ident['benchmark']}_{ident['copy']}",
             "configs": per_config_reports(trial_dir)})

    trials = []
    for (fuzzer, rts, cts, benchmark, trial), parts in copies.items():
        if len(parts) == 1:
            totals = parts[0]["totals"]
            lines, branches = parts[0]["lines"], parts[0]["branches"]
            values = {m: totals[m][0] for m in METRICS if m in totals}
            instrumented = {m: totals[m][1] for m in METRICS if m in totals}
        else:
            lines = set().union(*(p["lines"] for p in parts))
            branches = set().union(*(p["branches"] for p in parts))
            values = {"lines": len(lines), "branches": len(branches)}
            instrumented = {m: max(p["totals"][m][1] for p in parts) for m in ("lines", "branches")}
        trials.append({"arm": arm_name(fuzzer, rts, cts), "fuzzer": fuzzer, "rts": rts, "cts": cts,
                       "benchmark": benchmark, "trial": trial, "copies": len(parts),
                       "values": values, "instrumented": instrumented,
                       "line_set": lines, "branch_set": branches,
                       # for the HTML source reports (coverage_html.py)
                       "dirs": [p["dir"] for p in parts], "cts_benchmarks": [p["cts_benchmark"] for p in parts],
                       "configs": parts[0]["configs"] if len(parts) == 1 else []})
    return trials


def per_config_reports(trial_dir):
    """[(config index, covered branches)] of a runtime-strategy trial's configurations,
    from config_<i>/coverage/report.json (written by post_analysis.py --per-config-coverage)."""
    out = []
    for entry in sorted(os.listdir(trial_dir)):
        match = re.match(r"^config_(\d+)$", entry)
        report = os.path.join(trial_dir, entry, "coverage", "report.json")
        if match and os.path.isfile(report):
            try:
                out.append((int(match.group(1)), parse_lcov_sets(report)[1]))
            except OSError:
                pass
    return out


def planned_trials(experiment_path):
    """{(arm, benchmark): trials planned} from the experiment state, or {} without one."""
    import pickle
    state_path = os.path.join(experiment_path, "experiment_state.pkl")
    if not os.path.isfile(state_path):
        return {}, None
    try:
        with open(state_path, "rb") as f:
            state = pickle.load(f)
    except Exception:
        return {}, None
    planned = Counter()
    for fuzzer, rts, cts_benchmark, *_ in state.get("trial_tasks", []):
        match = CTS_BENCHMARK.match(cts_benchmark)
        if not match or match.group("bin_no") != "0":
            continue
        planned[(arm_name(fuzzer, rts, match.group("cts")), match.group("benchmark"))] += 1
    return dict(planned), state


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def a12(x, y):
    """Vargha-Delaney A12: probability that a random value of x beats one of y (ties count half)."""
    if not len(x) or not len(y):
        return float("nan")
    greater = sum(1 for a in x for b in y if a > b)
    ties = sum(1 for a in x for b in y if a == b)
    return (greater + 0.5 * ties) / (len(x) * len(y))


def a12_magnitude(value):
    d = abs(value - 0.5)
    return "negligible" if d < 0.06 else "small" if d < 0.14 else "medium" if d < 0.21 else "large"


def mann_whitney(x, y, alternative="two-sided"):
    """Mann-Whitney U p-value (exact for small samples without ties, as scipy decides); 1 when it cannot be computed."""
    if len(x) < 1 or len(y) < 1:
        return float("nan")
    if len(set(x) | set(y)) == 1:
        return 1.0
    try:
        return float(stats.mannwhitneyu(x, y, alternative=alternative).pvalue)
    except ValueError:
        return 1.0


def min_two_sided_p(n, m):
    """Smallest p-value an exact two-sided Mann-Whitney U test can give with n and m trials."""
    if n < 1 or m < 1:
        return float("nan")
    return min(1.0, 2.0 / math.comb(n + m, n))


def holm(pvalues):
    """Holm-Bonferroni adjusted p-values, in the given order (NaN stays NaN)."""
    idx = [i for i, p in enumerate(pvalues) if not math.isnan(p)]
    adjusted = [float("nan")] * len(pvalues)
    running = 0.0
    m = len(idx)
    for rank, i in enumerate(sorted(idx, key=lambda i: pvalues[i])):
        running = max(running, min(1.0, (m - rank) * pvalues[i]))
        adjusted[i] = running
    return adjusted


def dunn(groups):
    """Dunn's test (two-sided, tie-corrected) for every pair of groups; {(i, j): p}."""
    values = np.concatenate([np.asarray(g, dtype=float) for g in groups])
    n_total = len(values)
    ranks = stats.rankdata(values)
    _, tie_counts = np.unique(values, return_counts=True)
    tie_term = float(np.sum(tie_counts ** 3 - tie_counts)) / (12.0 * (n_total - 1)) if n_total > 1 else 0.0
    sigma2 = n_total * (n_total + 1) / 12.0 - tie_term
    mean_ranks, start = [], 0
    for g in groups:
        mean_ranks.append(float(np.mean(ranks[start:start + len(g)])))
        start += len(g)
    out = {}
    for i, j in itertools.combinations(range(len(groups)), 2):
        se = math.sqrt(max(sigma2, 0.0) * (1.0 / len(groups[i]) + 1.0 / len(groups[j])))
        z = abs(mean_ranks[i] - mean_ranks[j]) / se if se > 0 else 0.0
        out[(i, j)] = float(2 * stats.norm.sf(z))
    return out


def rank_desc(values):
    """Ranks with 1 for the largest value, ties sharing the average rank."""
    return list(stats.rankdata([-v for v in values], method="average"))


def nemenyi_cd(k, n_blocks, alpha=ALPHA):
    """Nemenyi critical difference of average ranks for k arms over n_blocks benchmarks."""
    if k < 2 or n_blocks < 1:
        return float("nan")
    q = stats.studentized_range.ppf(1 - alpha, k, np.inf) / math.sqrt(2)
    return float(q * math.sqrt(k * (k + 1) / (6.0 * n_blocks)))


def nemenyi_p(avg_ranks, n_blocks):
    """Pairwise Nemenyi p-values from average ranks; {(i, j): p}."""
    k = len(avg_ranks)
    se = math.sqrt(k * (k + 1) / (6.0 * n_blocks))
    out = {}
    for i, j in itertools.combinations(range(k), 2):
        q = abs(avg_ranks[i] - avg_ranks[j]) / se * math.sqrt(2)
        out[(i, j)] = float(stats.studentized_range.sf(q, k, np.inf))
    return out


def cd_cliques(names, avg_ranks, cd):
    """Maximal runs of arms (sorted by rank) whose average ranks lie within cd of each other."""
    order = sorted(range(len(names)), key=lambda i: avg_ranks[i])
    cliques = []
    for a in range(len(order)):
        b = a
        while b + 1 < len(order) and avg_ranks[order[b + 1]] - avg_ranks[order[a]] < cd:
            b += 1
        if b > a and not any(s <= a and b <= e for s, e in cliques):
            cliques.append((a, b))
    return [[order[i] for i in range(s, e + 1)] for s, e in cliques]


def spearman(x, y):
    """Spearman's rho with a two-sided p-value, exact (all permutations) for up to 8 values;
    scipy's t approximation is far too small for the handful of arms an experiment has."""
    rho = float(stats.spearmanr(x, y)[0])
    if len(x) > 8:
        return rho, float(stats.spearmanr(x, y)[1])
    rx = stats.rankdata(x)
    perms = list(itertools.permutations(stats.rankdata(y)))
    extreme = sum(1 for p in perms if abs(float(np.corrcoef(rx, p)[0, 1])) >= abs(rho) - 1e-12)
    return rho, extreme / len(perms)


def iqr(values):
    return float(np.percentile(values, 75) - np.percentile(values, 25)) if len(values) else float("nan")


def cv(values):
    mean = float(np.mean(values)) if len(values) else float("nan")
    return float(np.std(values, ddof=1) / mean * 100) if len(values) > 1 and mean else float("nan")


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def arm_sort_key(arm, trial_info):
    info = trial_info[arm]
    return (info["fuzzer"], info["cts"] != "default", info["cts"], info["rts"] != "default", info["rts"])


def analyse_benchmark(benchmark, trials, arms, metric, reference_pairs):
    """Every per-benchmark statistic for the arms that have trials on this benchmark."""
    by_arm = defaultdict(list)
    for t in trials:
        by_arm[t["arm"]].append(t)
    arms = [a for a in arms if a in by_arm]
    values = {a: [t["values"][metric] for t in sorted(by_arm[a], key=lambda t: t["trial"])
                  if metric in t["values"]] for a in arms}
    arms = [a for a in arms if values[a]]
    values = {a: values[a] for a in arms}
    medians = {a: float(np.median(values[a])) for a in arms}
    instrumented = max((t["instrumented"].get(metric, 0) for t in trials), default=0)

    result = {"benchmark": benchmark, "arms": arms, "values": values, "medians": medians,
              "instrumented": instrumented}
    if not arms:
        return result

    # Ranking by median, normalized score, relative coverage
    ranks = dict(zip(arms, rank_desc([medians[a] for a in arms])))
    best_median = max(medians.values())
    best_trial = max(max(v) for v in values.values())
    result["ranks"] = ranks
    result["normalized"] = {a: medians[a] / best_median * 100 if best_median else float("nan") for a in arms}
    result["relative"] = {a: float(np.median([v / best_trial * 100 for v in values[a]])) if best_trial
                          else float("nan") for a in arms}
    result["first_place"] = [a for a in arms if medians[a] == best_median]

    # Pairwise two-sided Mann-Whitney U with Holm, A12, minimum achievable p
    pairs = list(itertools.combinations(arms, 2))
    raw = [mann_whitney(values[a], values[b]) for a, b in pairs]
    adj = holm(raw)
    result["mwu"] = {pair: {"p": p, "p_holm": q} for pair, p, q in zip(pairs, raw, adj)}
    result["a12"] = {(a, b): a12(values[a], values[b]) for a in arms for b in arms if a != b}

    # One-sided "better than": per pair, the test in the direction of the higher median, Holm over pairs
    one_raw, directions = [], []
    for a, b in pairs:
        better, worse = (a, b) if np.mean(stats.rankdata(values[a] + values[b])[:len(values[a])]) >= \
            np.mean(stats.rankdata(values[a] + values[b])[len(values[a]):]) else (b, a)
        directions.append((better, worse))
        one_raw.append(mann_whitney(values[better], values[worse], alternative="greater"))
    one_adj = holm(one_raw)
    better_than = {(a, b): 0 for a in arms for b in arms if a != b}
    for (better, worse), q in zip(directions, one_adj):
        if q < ALPHA:
            better_than[(better, worse)] = 1
    result["better_than"] = better_than
    result["wins"] = {a: sum(better_than[(a, b)] for b in arms if b != a) for a in arms}

    # Comparisons against the default runtime strategy and the baseline fuzzer
    comps = []
    for a, b, kind in reference_pairs:
        if a in values and b in values:
            comps.append({"arm": a, "reference": b, "kind": kind,
                          "median": medians[a], "ref_median": medians[b],
                          "delta": (medians[a] - medians[b]) / medians[b] * 100 if medians[b] else float("nan"),
                          "a12": a12(values[a], values[b]), "p": mann_whitney(values[a], values[b]),
                          "floor": min_two_sided_p(len(values[a]), len(values[b]))})
    for c, q in zip(comps, holm([c["p"] for c in comps])):
        c["p_holm"] = q
    result["comparisons"] = comps

    # Kruskal-Wallis, then Dunn with Holm only when it rejects
    kw = None
    if len(arms) >= 3 and all(len(values[a]) >= 2 for a in arms):
        try:
            h, p = stats.kruskal(*[values[a] for a in arms])
            kw = {"h": float(h), "p": float(p)}
        except ValueError:
            kw = {"h": 0.0, "p": 1.0}
        if kw["p"] < ALPHA:
            d = dunn([values[a] for a in arms])
            keys = list(d)
            adj_d = holm([d[k] for k in keys])
            kw["dunn"] = {(arms[i], arms[j]): q for (i, j), q in zip(keys, adj_d)}
    result["kruskal"] = kw

    # Variability
    result["spread"] = {a: {"iqr": iqr(values[a]), "cv": cv(values[a]),
                            "min": min(values[a]), "max": max(values[a]), "n": len(values[a])} for a in arms}

    # Coverage sets: union of each arm's trials; unique, pairwise unique, Jaccard, UpSet
    set_key = "branch_set" if metric != "lines" else "line_set"
    unions = {a: set().union(*(t[set_key] for t in by_arm[a])) for a in arms}
    owners = defaultdict(list)
    for a in arms:
        for item in unions[a]:
            owners[item].append(a)
    unique = Counter(o[0] for o in owners.values() if len(o) == 1)
    result["set_metric"] = "lines" if metric == "lines" else "branches"
    result["union"] = {a: len(unions[a]) for a in arms}
    result["unique"] = {a: unique.get(a, 0) for a in arms}
    result["pairwise_unique"] = {(row, col): len(unions[col] - unions[row])
                                 for row in arms for col in arms if row != col}
    result["jaccard"] = {(a, b): (len(unions[a] & unions[b]) / len(unions[a] | unions[b]))
                         if unions[a] | unions[b] else float("nan")
                         for a in arms for b in arms if a != b}
    result["upset"] = Counter(tuple(sorted(o, key=arms.index)) for o in owners.values()).most_common()
    max_unique = max(result["unique"].values())
    result["unique_normalized"] = {a: result["unique"][a] / max_unique * 100 if max_unique else float("nan")
                                   for a in arms}
    result["unique_ranks"] = dict(zip(arms, rank_desc([result["unique"][a] for a in arms])))

    # Union of a runtime strategy's configurations against its best single configuration
    configs = []
    for a in arms:
        for t in by_arm[a]:
            if len(t["configs"]) >= 2:
                sizes = [len(s) for _, s in t["configs"]]
                union = len(set().union(*(s for _, s in t["configs"])))
                configs.append({"arm": a, "trial": t["trial"], "configs": len(sizes), "best_single": max(sizes),
                                "union": union, "trial_total": len(t["branch_set"])})
    result["config_union"] = configs

    # Rankings by every metric, for the correlation between rankings
    result["metric_ranks"] = {}
    for m in METRICS:
        meds = {a: float(np.median([t["values"][m] for t in by_arm[a]]))
                for a in arms if all(m in t["values"] for t in by_arm[a])}
        if len(meds) == len(arms):
            result["metric_ranks"][m] = dict(zip(arms, rank_desc([meds[a] for a in arms])))
    return result


def across_benchmarks(per_benchmark, arms, view_name):
    """Friedman test, Nemenyi critical difference and aggregate rankings over the
    benchmarks on which every arm of the view has trials."""
    blocks = [r for r in per_benchmark if all(a in r.get("medians", {}) for a in arms)]
    out = {"view": view_name, "arms": arms, "benchmarks": [r["benchmark"] for r in blocks]}
    if not blocks or not arms:
        return out
    n = len(blocks)
    # Ranks within the view (re-ranked among its own arms)
    rank_rows = [dict(zip(arms, rank_desc([r["medians"][a] for a in arms]))) for r in blocks]
    avg_rank = {a: float(np.mean([row[a] for row in rank_rows])) for a in arms}
    out["avg_rank"] = avg_rank
    out["rank_rows"] = rank_rows
    best = [max(r["medians"][a] for a in arms) for r in blocks]
    out["avg_normalized"] = {a: float(np.mean([r["medians"][a] / b * 100 for r, b in zip(blocks, best) if b]))
                             for a in arms}
    out["first_places"] = {a: sum(1 for r, b in zip(blocks, best) if r["medians"][a] == b) for a in arms}

    # Unique coverage within the view's arms
    unique_rank_rows, unique_norm_rows, total_unique = [], [], Counter()
    for r in blocks:
        u = {a: r["unique"][a] for a in arms} if set(arms) == set(r["arms"]) else None
        if u is None:
            # The view has fewer arms than the benchmark: recompute unique coverage among them.
            u = view_unique(r, arms)
        unique_rank_rows.append(dict(zip(arms, rank_desc([u[a] for a in arms]))))
        m = max(u.values())
        if m:
            unique_norm_rows.append({a: u[a] / m * 100 for a in arms})
        total_unique.update(u)
    out["unique_avg_rank"] = {a: float(np.mean([row[a] for row in unique_rank_rows])) for a in arms}
    out["unique_avg_normalized"] = {a: float(np.mean([row[a] for row in unique_norm_rows]))
                                    if unique_norm_rows else float("nan") for a in arms}
    out["unique_total"] = {a: total_unique[a] for a in arms}
    out["wins"] = {a: sum(r["better_than"].get((a, b), 0) for r in blocks for b in arms if b != a) for a in arms}

    k = len(arms)
    if k >= 3 and n >= 2:
        try:
            chi2, p = stats.friedmanchisquare(*[[r["medians"][a] for r in blocks] for a in arms])
            out["friedman"] = {"chi2": float(chi2), "p": float(p)}
        except ValueError:
            out["friedman"] = {"chi2": 0.0, "p": 1.0}
    if k >= 2:
        cd = nemenyi_cd(k, n)
        out["cd"] = cd
        ranks = [avg_rank[a] for a in arms]
        out["cliques"] = [[arms[i] for i in c] for c in cd_cliques(arms, ranks, cd)]
        out["nemenyi"] = {(arms[i], arms[j]): p for (i, j), p in nemenyi_p(ranks, n).items()}

    # Correlation between rankings (over arms, using the average ranks)
    corr = []
    def add(name, x, y):
        if len(x) >= 3 and len(set(x)) > 1 and len(set(y)) > 1:
            rho, prho = spearman(x, y)
            tau, ptau = stats.kendalltau(x, y)
            corr.append({"pair": name, "spearman": float(rho), "spearman_p": float(prho),
                         "kendall": float(tau), "kendall_p": float(ptau), "n": len(x)})
    add(f"median {blocks[0]['set_metric']} rank vs unique {blocks[0]['set_metric']} rank",
        [avg_rank[a] for a in arms], [out["unique_avg_rank"][a] for a in arms])
    metric_avg = {}
    for m in METRICS:
        if all(m in r["metric_ranks"] for r in blocks):
            rows = [dict(zip(arms, rank_desc([-r["metric_ranks"][m][a] for a in arms]))) for r in blocks]
            metric_avg[m] = {a: float(np.mean([row[a] for row in rows])) for a in arms}
    for m1, m2 in itertools.combinations(metric_avg, 2):
        add(f"{m1} rank vs {m2} rank", [metric_avg[m1][a] for a in arms], [metric_avg[m2][a] for a in arms])
    out["correlations"] = corr
    return out


def view_unique(result, arms):
    """Unique coverage among a subset of a benchmark's arms, from the UpSet intersections."""
    counts = Counter()
    for owners, n in result["upset"]:
        inside = [a for a in owners if a in arms]
        if len(inside) == 1:
            counts[inside[0]] += n
    return {a: counts.get(a, 0) for a in arms}


def reference_pairs(arms, info, baseline):
    """(arm, reference, kind): each runtime strategy against its fuzzer's default, and each
    fuzzer's default against the baseline fuzzer's default (same compile-time strategy)."""
    pairs = []
    for a in arms:
        f, rts, cts = info[a]["fuzzer"], info[a]["rts"], info[a]["cts"]
        default = arm_name(f, "default", cts)
        if rts != "default" and default in arms:
            pairs.append((a, default, "runtime strategy vs default"))
        if rts == "default" and baseline and f != baseline and arm_name(baseline, "default", cts) in arms:
            pairs.append((a, arm_name(baseline, "default", cts), f"fuzzer vs {baseline}"))
    return pairs


def found_bugs(experiment_path):
    """{(fuzzer, benchmark): set of crash keys} from afl-collect's crashes.db files."""
    out = {}
    root = os.path.join(experiment_path, "bug-triaging")
    if not os.path.isdir(root):
        return out
    for triager in os.listdir(root):
        output = os.path.join(root, triager, "output")
        if not os.path.isdir(output):
            continue
        for pooled in os.listdir(output):
            db = os.path.join(output, pooled, "crashes.db")
            if not os.path.isfile(db):
                continue
            match = re.match(r"^(?P<fuzzer>.+?)_(?P<benchmark>cts_.+_\d+)$", pooled)
            if not match:
                continue
            m = CTS_BENCHMARK.match(match.group("benchmark"))
            key = (match.group("fuzzer"), m.group("benchmark") if m else match.group("benchmark"))
            try:
                con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
                table = con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchone()[0]
                cols = [c[1] for c in con.execute(f"PRAGMA table_info({table})")]
                col = next((c for c in cols if c.lower() == "hash"), None) or \
                    next((c for c in cols if "class" in c.lower()), cols[0])
                keys = {r[0] for r in con.execute(f"SELECT {col} FROM {table}")}
                con.close()
            except Exception as e:
                logging.warning(f"Cannot read {db}: {e}")
                continue
            out.setdefault(key, set()).update(keys)
    return out


def benchmark_properties(benchmark, project_root, instrumented_by_metric):
    props = {"benchmark": benchmark}
    bdir = os.path.join(project_root, "benchmarks", benchmark) if project_root else None
    if bdir and os.path.isdir(bdir):
        d = os.path.join(bdir, "dict")
        if os.path.isfile(d):
            with open(d, "r", encoding="utf-8", errors="replace") as f:
                props["dict"] = sum(1 for l in f if l.strip() and not l.lstrip().startswith("#"))
        seed = os.path.join(bdir, "seed")
        props["seeds"] = len(os.listdir(seed)) if os.path.isdir(seed) else 0
        for key, name in (("rt_options", "rt_grammar.json"), ("ct_options", "ct_grammar.json")):
            p = os.path.join(bdir, name)
            if os.path.isfile(p):
                with open(p, "r", encoding="utf-8") as f:
                    props[key] = len(json.load(f).get("options", []))
        rt = os.path.join(bdir, "run_target.sh")
        if os.path.isfile(rt):
            with open(rt, "r", encoding="utf-8") as f:
                props["run_target"] = f.read().strip()
    props.update({f"instrumented_{m}": v for m, v in instrumented_by_metric.items()})
    return props


def analyse(experiment_path, metric="branches", baseline=None):
    trials = load_trials(experiment_path)
    if not trials:
        raise RuntimeError(f"No trial with a coverage report under {experiment_path}/data")
    planned, state = planned_trials(experiment_path)
    info = {}
    for t in trials:
        info.setdefault(t["arm"], {"fuzzer": t["fuzzer"], "rts": t["rts"], "cts": t["cts"]})
    arms = sorted(info, key=lambda a: arm_sort_key(a, info))
    benchmarks = sorted({t["benchmark"] for t in trials})
    fuzzers = sorted({info[a]["fuzzer"] for a in arms})
    if baseline is None:
        baseline = "aflplusplus" if "aflplusplus" in fuzzers else fuzzers[0]
    pairs = reference_pairs(arms, info, baseline)

    per_benchmark = []
    for b in benchmarks:
        bt = [t for t in trials if t["benchmark"] == b]
        per_benchmark.append(analyse_benchmark(b, bt, arms, metric, pairs))

    # Views: all arms; per fuzzer, its runtime strategies; the fuzzers under their default strategies
    views = [across_benchmarks(per_benchmark, [a for a in arms if all(a in r["medians"] for r in per_benchmark)]
                               or arms, "All arms")]
    for f in fuzzers:
        rts_arms = [a for a in arms if info[a]["fuzzer"] == f and info[a]["cts"] == "default"]
        if len(rts_arms) >= 2:
            views.append(across_benchmarks(per_benchmark, rts_arms, f"Runtime strategies of {f}"))
    fuzzer_arms = [a for a in arms if info[a]["rts"] == "default" and info[a]["cts"] == "default"]
    if len(set(info[a]["fuzzer"] for a in fuzzer_arms)) >= 2:
        views.append(across_benchmarks(per_benchmark, fuzzer_arms, "Fuzzers (default runtime strategy)"))

    # Low-sample flag: fewer than 80% of the most trials on the benchmark, or of the planned trials
    low_sample = []
    for r in per_benchmark:
        if not r["arms"]:
            continue
        most = max(len(v) for v in r["values"].values())
        for a in r["arms"]:
            n = len(r["values"][a])
            plan = planned.get((a, r["benchmark"]))
            if n < LOW_SAMPLE_FRACTION * most or (plan and n < LOW_SAMPLE_FRACTION * plan):
                low_sample.append({"arm": a, "benchmark": r["benchmark"], "trials": n,
                                   "most": most, "planned": plan})
    missing = [{"arm": a, "benchmark": b, "planned": n} for (a, b), n in planned.items()
               if not any(a in r["medians"] for r in per_benchmark if r["benchmark"] == b)]

    instrumented = {b: {m: max((t["instrumented"].get(m, 0) for t in trials if t["benchmark"] == b), default=0)
                        for m in METRICS} for b in benchmarks}
    project_root = state.get("project_root") if state else None
    properties = [benchmark_properties(b, project_root, instrumented[b]) for b in benchmarks]

    return {"experiment_path": experiment_path, "experiment": os.path.basename(os.path.normpath(experiment_path)),
            "metric": metric, "baseline": baseline, "arms": arms, "info": info, "benchmarks": benchmarks,
            "trials": trials, "per_benchmark": per_benchmark, "views": views, "low_sample": low_sample,
            "missing": missing, "properties": properties, "bugs": found_bugs(experiment_path),
            "trial_counts": Counter((t["arm"], t["benchmark"]) for t in trials)}


def compare_experiments(a, b):
    """Reproducibility / sensitivity: the same rankings in two experiments (analyse() results)."""
    va, vb = a["views"][0], b["views"][0]
    common = [x for x in va.get("arms", []) if x in vb.get("arms", [])]
    out = {"other": b["experiment"], "arms": common, "overall": None, "per_benchmark": []}
    if len(common) >= 2 and "avg_rank" in va and "avg_rank" in vb:
        x, y = [va["avg_rank"][c] for c in common], [vb["avg_rank"][c] for c in common]
        tau, p = stats.kendalltau(x, y) if len(set(x)) > 1 and len(set(y)) > 1 else (float("nan"), float("nan"))
        out["overall"] = {"kendall": float(tau), "p": float(p), "ranks_a": dict(zip(common, x)),
                          "ranks_b": dict(zip(common, y)),
                          "groups_a": va.get("cliques", []), "groups_b": vb.get("cliques", [])}
    rb = {r["benchmark"]: r for r in b["per_benchmark"]}
    for r in a["per_benchmark"]:
        o = rb.get(r["benchmark"])
        if not o:
            continue
        arms = [x for x in r["arms"] if x in o["arms"]]
        if len(arms) < 2:
            continue
        x = rank_desc([r["medians"][c] for c in arms])
        y = rank_desc([o["medians"][c] for c in arms])
        tau = stats.kendalltau(x, y)[0] if len(set(x)) > 1 and len(set(y)) > 1 else float("nan")
        sig_a = {p for p, v in r["mwu"].items() if v["p_holm"] < ALPHA and all(c in arms for c in p)}
        sig_b = {p for p, v in o["mwu"].items() if v["p_holm"] < ALPHA and all(c in arms for c in p)}
        out["per_benchmark"].append({"benchmark": r["benchmark"], "kendall": float(tau),
                                     "same_order": x == y, "sig_changed": sorted(sig_a ^ sig_b)})
    return out


# ---------------------------------------------------------------------------
# Figures (matplotlib SVG, recoloured to the page's CSS tokens)
# ---------------------------------------------------------------------------

# Placeholder colours replaced by CSS variables, so the figures follow light and dark mode.
INK, MUTED, GRID, S1, S1_LIGHT = "#010101", "#020202", "#030303", "#040404", "#050505"
TOKENS = {INK: "var(--ink)", MUTED: "var(--muted)", GRID: "var(--grid)", S1: "var(--series-1)",
          S1_LIGHT: "var(--series-1-light)"}


def _plt():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"svg.fonttype": "none", "font.family": "sans-serif", "font.size": 10,
                         "axes.edgecolor": GRID, "axes.labelcolor": INK, "xtick.color": MUTED,
                         "ytick.color": MUTED, "text.color": INK, "axes.spines.top": False,
                         "axes.spines.right": False})
    return plt


def to_svg(fig):
    plt = _plt()
    buf = io.StringIO()
    fig.savefig(buf, format="svg", transparent=True, bbox_inches="tight")
    plt.close(fig)
    svg = buf.getvalue()
    svg = svg[svg.index("<svg"):]
    for placeholder, var in TOKENS.items():
        svg = svg.replace(placeholder, var)
    return f'<figure class="fig">{svg}</figure>'


def box_plot(result, metric):
    plt = _plt()
    arms = sorted(result["arms"], key=lambda a: result["medians"][a])
    fig, ax = plt.subplots(figsize=(7.5, 0.45 * len(arms) + 0.9))
    for y, a in enumerate(arms):
        v = result["values"][a]
        if len(v) >= 5:
            ax.boxplot([v], positions=[y], vert=False, widths=0.5, patch_artist=True, showfliers=False,
                       boxprops=dict(facecolor=S1_LIGHT, edgecolor=S1, linewidth=1),
                       medianprops=dict(color=INK, linewidth=2), whiskerprops=dict(color=S1),
                       capprops=dict(color=S1))
        else:
            ax.plot([min(v), max(v)], [y, y], color=S1, linewidth=2, solid_capstyle="round")
            ax.plot([np.median(v)], [y], marker="|", markersize=16, color=INK, markeredgewidth=2.5)
        ax.scatter(v, [y] * len(v), s=22, color=S1, edgecolor="white", linewidth=0.8, zorder=3)
    ax.set_yticks(range(len(arms)), arms)
    ax.set_xlabel(f"{metric} covered (final, per trial)")
    ax.grid(axis="x", color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)
    return to_svg(fig)


def unique_bar_plot(result):
    plt = _plt()
    arms = sorted(result["arms"], key=lambda a: result["union"][a])
    fig, ax = plt.subplots(figsize=(7.5, 0.45 * len(arms) + 1.0))
    y = np.arange(len(arms))
    ax.barh(y, [result["union"][a] for a in arms], color=S1_LIGHT, height=0.6, label="covered by any trial (union)")
    ax.barh(y, [result["unique"][a] for a in arms], color=S1, height=0.6, label="covered by this arm only")
    for i, a in enumerate(arms):
        ax.text(result["union"][a], i, f"  {result['unique'][a]:,} unique / {result['union'][a]:,}",
                va="center", fontsize=9, color=MUTED)
    ax.set_yticks(y, arms)
    ax.set_xlabel(f"{result['set_metric']}")
    ax.set_xlim(0, max(result["union"].values()) * 1.35 or 1)
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.0), ncol=2, frameon=False, fontsize=9)
    ax.grid(axis="x", color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)
    return to_svg(fig)


def upset_plot(result, top=15):
    plt = _plt()
    arms = result["arms"]
    subsets = result["upset"][:top]
    if not subsets:
        return ""
    fig, (ax_bar, ax_dot) = plt.subplots(2, 1, figsize=(max(6, 0.5 * len(subsets) + 3), 2.6 + 0.3 * len(arms)),
                                         gridspec_kw={"height_ratios": [2.2, 0.3 * len(arms) + 0.4]},
                                         sharex=True)
    x = np.arange(len(subsets))
    ax_bar.bar(x, [n for _, n in subsets], color=S1, width=0.6)
    for i, (_, n) in enumerate(subsets):
        ax_bar.text(i, n, f"{n:,}", ha="center", va="bottom", fontsize=8, color=MUTED)
    ax_bar.set_ylabel(result["set_metric"])
    ax_bar.grid(axis="y", color=GRID, linewidth=0.6)
    ax_bar.set_axisbelow(True)
    for i, (owners, _) in enumerate(subsets):
        ys = [arms.index(a) for a in owners]
        ax_dot.scatter([i] * len(arms), range(len(arms)), s=40, color=GRID, zorder=1)
        ax_dot.scatter([i] * len(ys), ys, s=40, color=INK, zorder=2)
        if len(ys) > 1:
            ax_dot.plot([i, i], [min(ys), max(ys)], color=INK, linewidth=1.5, zorder=2)
    ax_dot.set_yticks(range(len(arms)), arms)
    ax_dot.invert_yaxis()
    ax_dot.set_xticks([])
    for s in ("left", "bottom"):
        ax_dot.spines[s].set_visible(False)
    return to_svg(fig)


def cd_diagram(view):
    plt = _plt()
    arms, ranks, cd = view["arms"], view["avg_rank"], view["cd"]
    k = len(arms)
    order = sorted(arms, key=lambda a: ranks[a])
    fig, ax = plt.subplots(figsize=(5, 1.4 + 0.32 * k))
    lo, hi = 1, k
    ax.set_xlim(lo - 0.3, hi + 0.3)
    ax.hlines(0, lo, hi, color=INK, linewidth=1)
    for r in range(1, k + 1):
        ax.vlines(r, 0, 0.12, color=INK, linewidth=1)
        ax.text(r, 0.2, str(r), ha="center", va="bottom", fontsize=9, color=MUTED)
    # CD bar
    if not math.isnan(cd) and cd <= k - 1:
        ax.hlines(0.65, lo, lo + cd, color=INK, linewidth=2)
        ax.text(lo + cd / 2, 0.75, f"CD = {cd:.2f}", ha="center", va="bottom", fontsize=9)
    else:
        ax.text(lo, 0.65, f"CD = {cd:.2f} (wider than the whole rank range)", ha="left", va="bottom", fontsize=9)
    left = order[: (k + 1) // 2]
    right = order[(k + 1) // 2:]
    # Labels sit outside the rank axis, joined to their rank by an elbow line
    for i, a in enumerate(left):
        y = -0.45 - 0.32 * i
        ax.plot([ranks[a], ranks[a], lo - 0.25], [0, y, y], color=MUTED, linewidth=0.8, clip_on=False)
        ax.text(lo - 0.3, y, f"{a} ({ranks[a]:.2f})", ha="right", va="center", fontsize=9, clip_on=False)
    for i, a in enumerate(reversed(right)):
        y = -0.45 - 0.32 * i
        ax.plot([ranks[a], ranks[a], hi + 0.25], [0, y, y], color=MUTED, linewidth=0.8, clip_on=False)
        ax.text(hi + 0.3, y, f"({ranks[a]:.2f}) {a}", ha="left", va="center", fontsize=9, clip_on=False)
    for j, clique in enumerate(view.get("cliques", [])):
        rs = [ranks[a] for a in clique]
        ax.hlines(-0.15 - 0.1 * j, min(rs) - 0.03, max(rs) + 0.03, color=S1, linewidth=4)
    ax.set_ylim(-0.6 - 0.32 * max(len(left), len(right)), 1.1)
    ax.axis("off")
    return to_svg(fig)


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

def e(x):
    return html.escape(str(x))


def fmt(x, digits=2, pct=False):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "–"
    if isinstance(x, (int, np.integer)) and not pct:
        return f"{int(x):,}"
    s = f"{x:,.{digits}f}"
    return s + "%" if pct else s


def fmt_p(p):
    if p is None or (isinstance(p, float) and math.isnan(p)):
        return "–"
    return "<0.001" if p < 0.001 else f"{p:.3f}"


def p_eq(p):
    s = fmt_p(p)
    return f"p {s[0]} {s[1:]}" if s.startswith("<") else f"p = {s}"


def table(headers, rows, cls="", numeric_from=1):
    head = "".join(f'<th class="{"num" if i >= numeric_from else ""}">{h}</th>' for i, h in enumerate(headers))
    body = "".join("<tr>" + "".join(f'<td class="{"num" if i >= numeric_from else ""}">{c}</td>'
                                    for i, c in enumerate(r)) + "</tr>" for r in rows)
    return f'<div class="tw"><table class="{cls}"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def seq_bg(value, vmax):
    """Background for a sequential (one-hue) heat cell."""
    if vmax <= 0 or value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    t = max(0.0, min(1.0, value / vmax))
    return f' style="background: color-mix(in oklab, var(--series-1) {round(8 + 72 * t)}%, var(--surface));' \
           f'color: {"var(--on-strong)" if t > 0.55 else "var(--ink)"}"'


def div_bg(value):
    """Background for a diverging A12 cell: blue above 0.5, red below, gray at 0.5."""
    if value is None or math.isnan(value):
        return ""
    t = (value - 0.5) * 2
    colour = "var(--series-1)" if t >= 0 else "var(--neg)"
    pct = round(abs(t) * 75)
    return f' style="background: color-mix(in oklab, {colour} {pct}%, var(--mid));' \
           f'color: {"var(--on-strong)" if abs(t) > 0.6 else "var(--ink)"}"'


def matrix(arms, cell, title_fn=None, corner=""):
    head = "".join(f'<th class="rot"><span>{e(a)}</span></th>' for a in arms)
    rows = []
    for r in arms:
        cells = []
        for c in arms:
            if r == c:
                cells.append('<td class="diag"></td>')
            else:
                text, attrs = cell(r, c)
                tip = f' title="{e(title_fn(r, c))}"' if title_fn else ""
                cells.append(f"<td{attrs}{tip}>{text}</td>")
        rows.append(f'<tr><th class="rowh">{e(r)}</th>{"".join(cells)}</tr>')
    return f'<div class="tw"><table class="matrix"><thead><tr><th>{corner}</th>{head}</tr></thead>' \
           f'<tbody>{"".join(rows)}</tbody></table></div>'


CSS = """
:root{color-scheme:light;--page:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;
--grid:#e1e0d9;--rule:#c3c2b7;--series-1:#2a78d6;--series-1-light:#b7d3f6;--neg:#e34948;--mid:#f0efec;
--good:#0ca30c;--good-ink:#006300;--warn:#b07800;--on-strong:#fff;--border:rgba(11,11,11,.10)}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;--page:#0d0d0d;
--surface:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;--muted:#898781;--grid:#2c2c2a;--rule:#383835;--series-1:#3987e5;
--series-1-light:#1c3f6b;--neg:#e66767;--mid:#383835;--good:#0ca30c;--good-ink:#0ca30c;--warn:#fab219;
--on-strong:#fff;--border:rgba(255,255,255,.10)}}
:root[data-theme="dark"]{color-scheme:dark;--page:#0d0d0d;--surface:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;
--muted:#898781;--grid:#2c2c2a;--rule:#383835;--series-1:#3987e5;--series-1-light:#1c3f6b;--neg:#e66767;
--mid:#383835;--good:#0ca30c;--good-ink:#0ca30c;--warn:#fab219;--on-strong:#fff;--border:rgba(255,255,255,.10)}
*{box-sizing:border-box}
body{margin:0;background:var(--page);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1180px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:26px;margin:0 0 4px}h2{font-size:20px;margin:40px 0 8px;padding-top:8px;border-top:1px solid var(--rule)}
h3{font-size:16px;margin:24px 0 6px}h4{font-size:14px;margin:16px 0 4px;color:var(--ink2)}
p,li{color:var(--ink2);max-width:80ch}.sub{color:var(--muted);margin:0 0 16px}
nav{display:flex;flex-wrap:wrap;gap:6px 14px;margin:12px 0 0;font-size:14px}nav a{color:var(--series-1)}
section.card{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:16px 18px;margin:16px 0}
.tw{overflow-x:auto;margin:8px 0}
table{border-collapse:collapse;font-size:13px;background:var(--surface)}
th,td{padding:5px 9px;border-bottom:1px solid var(--grid);text-align:left;white-space:nowrap}
th{color:var(--ink2);font-weight:600}td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
table.matrix td{text-align:center;font-variant-numeric:tabular-nums;min-width:58px;border:2px solid var(--surface)}
table.matrix td.diag{background:var(--grid)}th.rowh{text-align:right}
th.rot{height:120px;vertical-align:bottom;padding:0 2px}th.rot span{writing-mode:vertical-rl;transform:rotate(180deg);display:inline-block}
td.sig{background:color-mix(in oklab,var(--good) 30%,var(--surface));font-weight:600}
.badge{display:inline-block;font-size:12px;padding:1px 7px;border-radius:999px;border:1px solid var(--rule);color:var(--ink2)}
.warn{border-left:3px solid var(--warn);padding:6px 12px;margin:10px 0;background:var(--surface);color:var(--ink2)}
.fig{margin:8px 0}.fig svg{max-width:100%;height:auto}
.legend{font-size:12px;color:var(--muted)}
details{margin:8px 0}summary{cursor:pointer;color:var(--ink2);font-weight:600}
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:16px}
"""


def render_html(res, comparison=None):
    metric = res["metric"]
    arms = res["arms"]
    info = res["info"]
    out = []
    w = out.append
    w(f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' "
      f"content='width=device-width,initial-scale=1'><title>Coverage statistics</title><style>{CSS}</style></head><body><main>")
    w(f"<h1>Coverage statistics: {e(res['experiment'])}</h1>")
    n_trials = len(res["trials"])
    w(f"<p class='sub'>{len(arms)} arms × {len(res['benchmarks'])} benchmarks, {n_trials} trials. Primary metric: "
      f"<b>{e(metric)} covered</b> at the end of each trial (llvm-cov report.txt). Significance level {ALPHA}, "
      f"Holm-corrected on every pairwise table. Baseline fuzzer: {e(res['baseline'])}.</p>")
    sections = [("overall", "Overall ranking"), ("benchmarks", "Per-benchmark results"),
                ("relative", "Relative coverage"), ("properties", "Benchmark properties"),
                ("bugs", "Found bugs"), ("power", "Trials and statistical power"), ("method", "Method notes")]
    if comparison:
        sections.insert(6, ("repro", "Reproducibility"))
    w("<nav>" + "".join(f"<a href='#{k}'>{e(t)}</a>" for k, t in sections) + "".join(
        f"<a href='#b-{e(r['benchmark'])}'>{e(r['benchmark'])}</a>" for r in res["per_benchmark"]) + "</nav>")

    warnings = power_warnings(res)
    for msg in warnings:
        w(f"<div class='warn'>{msg}</div>")

    # ---- Overall ranking ----
    w("<h2 id='overall'>Overall ranking</h2>")
    w("<p>Rankings across benchmarks, every benchmark counting equally. Each view only uses the benchmarks on "
      "which all of its arms have trials. A bar in the critical-difference diagram joins arms whose average "
      "ranks are closer than the Nemenyi critical difference, so they are not significantly different.</p>")
    for v in res["views"]:
        if "avg_rank" not in v:
            continue
        w(f"<section class='card'><h3>{e(v['view'])}</h3>")
        w(f"<p class='sub'>{len(v['arms'])} arms over {len(v['benchmarks'])} benchmark(s): "
          f"{e(', '.join(v['benchmarks']))}</p>")
        fr = v.get("friedman")
        if fr:
            verdict = "some arm ranks consistently differently" if fr["p"] < ALPHA else \
                "no evidence that any arm ranks consistently differently"
            w(f"<p><b>Friedman test:</b> χ² = {fmt(fr['chi2'])}, {p_eq(fr['p'])}: {verdict}.</p>")
        elif len(v["arms"]) < 3:
            w("<p><b>Friedman test:</b> needs at least 3 arms.</p>")
        else:
            w("<p><b>Friedman test:</b> needs at least 2 benchmarks.</p>")
        order = sorted(v["arms"], key=lambda a: (v["avg_rank"][a], -v["avg_normalized"][a]))
        rows = []
        for i, a in enumerate(order, 1):
            rows.append([f"{i}. {e(a)}", fmt(v["avg_rank"][a]), fmt(v["avg_normalized"][a], 1, pct=True),
                         v["first_places"][a], v["wins"][a], fmt(v["unique_avg_rank"][a]),
                         fmt(v["unique_total"][a]), fmt(v["unique_avg_normalized"][a], 1, pct=True)])
        w(table(["Arm", "Avg rank (median)", "Avg normalized score", "First places", "Wins (better-than)",
                 f"Avg rank (unique {res['per_benchmark'][0].get('set_metric', 'branches')})", "Total unique",
                 "Avg normalized unique"], rows))
        if "cd" in v:
            w(cd_diagram(v))
            groups = v.get("cliques") or []
            w(f"<p class='legend'>Critical difference {fmt(v['cd'])} average ranks (Nemenyi, α = {ALPHA}, "
              f"{len(v['arms'])} arms, {len(v['benchmarks'])} benchmarks). "
              f"{len(groups)} group(s) of arms not significantly different.</p>")
            if v.get("nemenyi"):
                w("<details><summary>Pairwise Nemenyi p-values</summary>")
                w(matrix(v["arms"], lambda r, c: (fmt_p(v["nemenyi"].get((r, c), v["nemenyi"].get((c, r)))),
                                                   " class='sig'" if v["nemenyi"].get((r, c), v["nemenyi"].get((c, r), 1)) < ALPHA else "")))
                w("</details>")
        if v.get("correlations"):
            w("<h4>Correlation between rankings</h4>")
            w(table(["Rankings compared", "Spearman ρ", "p", "Kendall τ", "p", "Arms"],
                    [[e(c["pair"]), fmt(c["spearman"]), fmt_p(c["spearman_p"]), fmt(c["kendall"]),
                      fmt_p(c["kendall_p"]), c["n"]] for c in v["correlations"]]))
        w("</section>")

    # ---- Per benchmark ----
    w("<h2 id='benchmarks'>Per-benchmark results</h2>")
    for r in res["per_benchmark"]:
        if not r["arms"]:
            continue
        render_benchmark(w, r, res)

    # ---- Relative coverage ----
    w("<h2 id='relative'>Relative coverage</h2>")
    w(f"<p>Each trial's {e(metric)} as a percentage of the best trial on its benchmark; the cell is the arm's "
      f"median. The last two columns summarise the arm over benchmarks.</p>")
    rows = []
    for a in arms:
        vals = [r["relative"].get(a) for r in res["per_benchmark"]]
        present = [x for x in vals if x is not None]
        rows.append([e(a)] + [fmt(x, 1, pct=True) for x in vals] +
                    [fmt(float(np.mean(present)), 1, pct=True) if present else "–",
                     fmt(float(np.median(present)), 1, pct=True) if present else "–"])
    w(table(["Arm"] + [e(b) for b in res["benchmarks"]] + ["Mean", "Median"], rows))

    # ---- Properties ----
    w("<h2 id='properties'>Benchmark properties</h2>")
    w("<p>Instrumented counts are the denominators of the coverage percentages (llvm-cov). Options are the "
      "runtime (rt_grammar.json) and compile-time (ct_grammar.json) options the benchmark's grammars describe.</p>")
    rows = [[e(p["benchmark"]), fmt(p.get("instrumented_branches")), fmt(p.get("instrumented_lines")),
             fmt(p.get("instrumented_regions")), fmt(p.get("instrumented_functions")), fmt(p.get("dict")),
             fmt(p.get("seeds")), fmt(p.get("rt_options")), fmt(p.get("ct_options")),
             f"<code>{e(p.get('run_target', ''))}</code>"] for p in res["properties"]]
    w(table(["Benchmark", "Instr. branches", "Instr. lines", "Instr. regions", "Instr. functions",
             "Dict entries", "Seeds", "Runtime options", "Compile-time options", "Target command"], rows))

    # ---- Bugs ----
    w("<h2 id='bugs'>Found bugs</h2>")
    if res["bugs"]:
        w("<p>Distinct crash keys from crash triage (afl-collect), pooled over a fuzzer's trials. A secondary "
          "metric only: crashes are sparse and one bug reached through different stacks can count more than "
          "once. Triage runs per fuzzer, not per runtime strategy, so runtime strategies are not separated.</p>")
        fz = sorted({f for f, _ in res["bugs"]})
        rows = []
        for b in res["benchmarks"]:
            sets = [res["bugs"].get((f, b), set()) for f in fz]
            rows.append([e(b)] + [fmt(len(s)) for s in sets] + [fmt(len(set().union(*sets)))])
        w(table(["Benchmark"] + [e(f) for f in fz] + ["Union"], rows))
    else:
        w("<p>No crash triage results in this experiment (run with --bug-triaging afl-collect).</p>")

    # ---- Reproducibility ----
    if comparison:
        render_comparison(w, comparison)

    # ---- Power ----
    w("<h2 id='power'>Trials and statistical power</h2>")
    w("<p>With n and m trials, an exact two-sided Mann-Whitney U test cannot give a p-value below 2 / C(n+m, n). "
      "With Holm over K pairs, the smallest adjusted p-value is K times that floor.</p>")
    rows = []
    for r in res["per_benchmark"]:
        if not r["arms"]:
            continue
        ns = [len(r["values"][a]) for a in r["arms"]]
        k_pairs = len(r["arms"]) * (len(r["arms"]) - 1) // 2
        floor = min_two_sided_p(min(ns), min(ns))
        rows.append([e(r["benchmark"]), f"{min(ns)}–{max(ns)}", fmt_p(floor), k_pairs,
                     fmt_p(min(1.0, floor * k_pairs)) if k_pairs else "–",
                     "no pairs (one arm)" if not k_pairs else
                     "yes" if min(1.0, floor * k_pairs) < ALPHA else "<b>no</b>"])
    w(table(["Benchmark", "Trials per arm", "Min p (two-sided)", "Pairs (Holm family)",
             "Min Holm-adjusted p", "Can any pair be significant?"], rows))
    if res["low_sample"] or res["missing"]:
        w("<h4>Low-sample arms</h4>")
        rows = [[e(x["arm"]), e(x["benchmark"]), x["trials"], x["most"], x["planned"] or "–"]
                for x in res["low_sample"]]
        rows += [[e(x["arm"]), e(x["benchmark"]), 0, "–", x["planned"]] for x in res["missing"]]
        w(table(["Arm", "Benchmark", "Trials with coverage", "Most on benchmark", "Planned"], rows, numeric_from=2))

    # ---- Method ----
    w("<h2 id='method'>Method notes</h2><ul>")
    for note in method_notes(res):
        w(f"<li>{note}</li>")
    w("</ul></main></body></html>")
    return "".join(out)


def render_benchmark(w, r, res):
    metric = res["metric"]
    b = r["benchmark"]
    arms = r["arms"]
    w(f"<section class='card' id='b-{e(b)}'><h3>{e(b)}</h3>")
    inst = r["instrumented"]
    rows = []
    for a in sorted(arms, key=lambda a: (r["ranks"][a], a)):
        s = r["spread"][a]
        flag = " <span class='badge'>low sample</span>" if any(
            x["arm"] == a and x["benchmark"] == b for x in res["low_sample"]) else ""
        rows.append([f"{fmt(r['ranks'][a], 1)}. {e(a)}{flag}", s["n"], fmt(r["medians"][a], 0),
                     fmt(r["medians"][a] / inst * 100, 2, pct=True) if inst else "–",
                     fmt(s["min"]), fmt(s["max"]), fmt(s["iqr"], 0), fmt(s["cv"], 2, pct=True),
                     fmt(r["normalized"][a], 1, pct=True), fmt(r["relative"][a], 1, pct=True),
                     fmt(r["unique"][a]), r["wins"][a], "★" if a in r["first_place"] else ""])
    w(table(["Rank. Arm", "Trials", f"Median {e(metric)}", "of instrumented", "Min", "Max", "IQR", "CV",
             "% of best median", "Median % of best trial", f"Unique {e(r['set_metric'])}", "Wins", "Best"], rows))
    w(f"<p class='legend'>Ranked by median {e(metric)} covered ({fmt(inst)} instrumented). Arms with 5 or more "
      f"trials are drawn as box plots (box = quartiles, whiskers = range), with fewer as a min–max line with the "
      f"median tick; dots are trials.</p>")
    w(box_plot(r, metric))

    if r["comparisons"]:
        w("<h4>Against the default</h4>")
        rows = []
        for c in r["comparisons"]:
            sig = c["p_holm"] < ALPHA
            rows.append([e(c["arm"]), e(c["reference"]), e(c["kind"]), fmt(c["median"], 0), fmt(c["ref_median"], 0),
                         fmt(c["delta"], 1, pct=True), f"{fmt(c['a12'])} ({a12_magnitude(c['a12'])})",
                         fmt_p(c["p"]), f"<b>{fmt_p(c['p_holm'])}</b>" if sig else fmt_p(c["p_holm"]),
                         fmt_p(c["floor"])])
        w(table(["Arm", "Reference", "Comparison", "Median", "Ref. median", "Δ median", "A12", "p",
                 "p (Holm)", "Min possible p"], rows, numeric_from=3))
        w("<p class='legend'>Two-sided Mann-Whitney U; A12 is the chance that a trial of the arm beats a trial of "
          "the reference (0.5 tie; ≥0.71 or ≤0.29 large). Holm over this table's comparisons.</p>")

    kw = r.get("kruskal")
    if kw:
        verdict = "at least one arm differs" if kw["p"] < ALPHA else "no evidence that any arm differs"
        w(f"<p><b>Kruskal-Wallis:</b> H = {fmt(kw['h'])}, {p_eq(kw['p'])}: {verdict}.")
        if "dunn" in kw:
            w(" Dunn's post-hoc test (Holm) below.</p>")
            w(matrix(arms, lambda x, y: (fmt_p(kw["dunn"].get((x, y), kw["dunn"].get((y, x)))),
                                         " class='sig'" if kw["dunn"].get((x, y), kw["dunn"].get((y, x), 1)) < ALPHA else "")))
        else:
            w(" Pairwise post-hoc tests are not run.</p>")

    w("<div class='grid2'><div>")
    w("<h4>Two-sided Mann-Whitney U, Holm-adjusted p</h4>")
    def mwu_cell(x, y):
        v = r["mwu"].get((x, y)) or r["mwu"].get((y, x))
        return fmt_p(v["p_holm"]), " class='sig'" if v["p_holm"] < ALPHA else ""
    w(matrix(arms, mwu_cell, lambda x, y: f"{x} vs {y}: raw p {fmt_p((r['mwu'].get((x, y)) or r['mwu'].get((y, x)))['p'])}"))
    w("<p class='legend'>Green: p &lt; 0.05 after Holm. Hover a cell for the raw p.</p></div><div>")
    w("<h4>Vargha-Delaney A12 (row vs column)</h4>")
    w(matrix(arms, lambda x, y: (fmt(r["a12"][(x, y)]), div_bg(r["a12"][(x, y)])),
             lambda x, y: f"P({x} beats {y}) = {fmt(r['a12'][(x, y)])}, {a12_magnitude(r['a12'][(x, y)])}"))
    w("<p class='legend'>Blue: the row arm tends to beat the column; red: it tends to lose; gray: tie (0.5).</p>")
    w("</div></div>")

    w("<h4>Better-than matrix (one-sided Mann-Whitney U, Holm)</h4>")
    w(matrix(arms, lambda x, y: ("1" if r["better_than"][(x, y)] else "0",
                                 " class='sig'" if r["better_than"][(x, y)] else ""), corner="row beats column"))
    w(f"<p class='legend'>Wins (row sums): " + ", ".join(f"{e(a)} {r['wins'][a]}" for a in arms) + "</p>")

    w(f"<h4>Unique coverage ({e(r['set_metric'])})</h4>")
    w(f"<p class='legend'>Union of each arm's trials; unique = covered by this arm and by no other arm on {e(b)}.</p>")
    w(unique_bar_plot(r))
    w("<div class='grid2'><div>")
    w(f"<h4>Pairwise unique: {e(r['set_metric'])} the column covered and the row did not</h4>")
    pmax = max(r["pairwise_unique"].values()) if r["pairwise_unique"] else 0
    w(matrix(arms, lambda x, y: (fmt(r["pairwise_unique"][(x, y)]), seq_bg(r["pairwise_unique"][(x, y)], pmax)),
             lambda x, y: f"{r['pairwise_unique'][(x, y)]:,} {r['set_metric']} lost switching from {y} to {x}"))
    w("</div><div><h4>Jaccard similarity of covered sets</h4>")
    w(matrix(arms, lambda x, y: (fmt(r["jaccard"][(x, y)], 3), seq_bg(r["jaccard"][(x, y)], 1.0))))
    w("</div></div>")
    w(f"<h4>UpSet: {e(r['set_metric'])} covered by exactly each set of arms</h4>")
    w(upset_plot(r))

    if r["config_union"]:
        w("<h4>Runtime configurations: union against best single configuration</h4>")
        rows = [[e(c["arm"]), c["trial"], c["configs"], fmt(c["best_single"]), fmt(c["union"]),
                 fmt((c["union"] - c["best_single"]) / c["best_single"] * 100 if c["best_single"] else float("nan"),
                     1, pct=True), fmt(c["trial_total"])] for c in r["config_union"]]
        w(table(["Arm", "Trial", "Configurations", "Best single", "Union", "Gain", "Trial report"], rows,
                numeric_from=1))
    w("</section>")


def render_comparison(w, c):
    w(f"<h2 id='repro'>Reproducibility: against {e(c['other'])}</h2>")
    o = c["overall"]
    if o:
        w(f"<p>Average ranks of the {len(c['arms'])} arms both experiments share. Kendall τ = {fmt(o['kendall'])} "
          f"({p_eq(o['p'])}); 1 means the same order.</p>")
        w(table(["Arm", "Avg rank here", f"Avg rank in {e(c['other'])}"],
                [[e(a), fmt(o["ranks_a"][a]), fmt(o["ranks_b"][a])] for a in c["arms"]]))
        def groups(gs):
            return "; ".join("{" + ", ".join(g) + "}" for g in gs) or "none (every pair differs)"
        same = sorted(map(sorted, o["groups_a"])) == sorted(map(sorted, o["groups_b"]))
        w(f"<p>Groups not significantly different (Nemenyi) here: {e(groups(o['groups_a']))}. "
          f"In {e(c['other'])}: {e(groups(o['groups_b']))}. {'Same groups.' if same else '<b>The groups changed.</b>'}</p>")
    rows = [[e(x["benchmark"]), fmt(x["kendall"]), "yes" if x["same_order"] else "no",
             e(", ".join(f"{p[0]} vs {p[1]}" for p in x["sig_changed"])) or "none"] for x in c["per_benchmark"]]
    if rows:
        w(table(["Benchmark", "Kendall τ of median ranks", "Same order", "Pairs whose significance changed"], rows))


def power_warnings(res):
    msgs = []
    floors = []
    for r in res["per_benchmark"]:
        if len(r["arms"]) < 2:
            continue
        n = min(len(v) for v in r["values"].values())
        k = len(r["arms"]) * (len(r["arms"]) - 1) // 2
        floors.append((r["benchmark"], n, min_two_sided_p(n, n), k))
    blocked = [f for f in floors if f[2] * max(f[3], 1) >= ALPHA]
    if blocked:
        names = ", ".join(f"{b} ({n} trials, {k} pairs)" for b, n, _, k in blocked)
        msgs.append(f"<b>No pairwise test can reach p &lt; {ALPHA} after Holm on: {e(names)}.</b> Their green "
                    f"cells can never appear, whatever the data; plan for more trials (see "
                    f"<a href='#power'>Trials and statistical power</a>).")
    for v in res["views"]:
        if "cd" in v and len(v["arms"]) >= 2 and v["cd"] >= len(v["arms"]) - 1:
            msgs.append(f"<b>{e(v['view'])}:</b> with {len(v['benchmarks'])} benchmark(s) the critical difference "
                        f"({fmt(v['cd'])}) spans the whole rank range, so the Nemenyi test cannot separate any arms.")
    if res["low_sample"] or res["missing"]:
        msgs.append(f"{len(res['low_sample']) + len(res['missing'])} arm/benchmark pair(s) have fewer than "
                    f"{int(LOW_SAMPLE_FRACTION * 100)}% of the trials (see <a href='#power'>low-sample arms</a>).")
    return msgs


def method_notes(res):
    notes = [
        f"Coverage values are the final {e(res['metric'])} covered per trial, from the TOTAL row of the trial's "
        f"<code>coverage/report.txt</code> (llvm-cov report). Covered sets (unique coverage, pairwise unique, "
        f"Jaccard, UpSet, configuration union) come from the LCOV export next to it "
        f"(<code>coverage/report.json</code>): a branch is a <code>BRDA</code> record with a non-zero count.",
        "An arm is a fuzzer under one runtime strategy (and compile-time strategy when not default), written "
        "<code>fuzzer[strategy]</code>; the default runtime strategy is the plain fuzzer name.",
        "Medians summarise trials; ranks are by median with ties sharing the average rank; rank 1 is best.",
        "Average normalized score: the arm's median as a percentage of the best median on the benchmark, "
        "averaged over benchmarks. Relative coverage: every trial as a percentage of the best single trial.",
        "The better-than matrix uses, for each pair, the one-sided test in the direction of the arm with the "
        "higher mean rank, Holm-corrected over the pairs; a 1 means the row arm is significantly better.",
        "Kruskal-Wallis is the omnibus test per benchmark; Dunn's tie-corrected post-hoc test with Holm only runs "
        "when it rejects.",
        "Friedman and Nemenyi use the per-benchmark medians and only the benchmarks on which every arm of the "
        "view has trials. The critical difference is q(α, k, ∞)/√2 · √(k(k+1)/6N).",
        "Unique coverage uses the union of all of an arm's trials, so an arm with more trials has a larger "
        "union; compare it only between arms with the same number of trials (see the low-sample flag). Average "
        "normalized unique score: unique count as a percentage of the largest unique count on the benchmark.",
        "Correlations between rankings are over arms (their average ranks), so with few arms the p-values are "
        "uninformative.",
        "A trial whose compile-time strategy built several copies of the benchmark is the union of its copies' "
        "lines and branches; regions and functions are not available for such trials.",
        "Union across runtime configurations is only shown for trials with per-configuration reports "
        "(post_analysis.py --per-config-coverage).",
    ]
    return notes


# ---------------------------------------------------------------------------
# CSV/JSON output and entry points
# ---------------------------------------------------------------------------

def write_tables(res, out_dir):
    import csv
    with open(os.path.join(out_dir, "trials.csv"), "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["benchmark", "arm", "fuzzer", "runtime_strategy", "compiletime", "trial", "copies"] +
                    [m for m in METRICS] + [f"instrumented_{m}" for m in METRICS])
        for t in sorted(res["trials"], key=lambda t: (t["benchmark"], t["arm"], t["trial"])):
            wr.writerow([t["benchmark"], t["arm"], t["fuzzer"], t["rts"], t["cts"], t["trial"], t["copies"]] +
                        [t["values"].get(m, "") for m in METRICS] + [t["instrumented"].get(m, "") for m in METRICS])
    with open(os.path.join(out_dir, "benchmark_ranking.csv"), "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["benchmark", "arm", "trials", "median", "min", "max", "iqr", "cv_percent", "rank",
                     "normalized_score", "relative_coverage", "unique", "union", "wins"])
        for r in res["per_benchmark"]:
            for a in r["arms"]:
                s = r["spread"][a]
                wr.writerow([r["benchmark"], a, s["n"], r["medians"][a], s["min"], s["max"], s["iqr"], s["cv"],
                             r["ranks"][a], r["normalized"][a], r["relative"][a], r["unique"][a], r["union"][a],
                             r["wins"][a]])
    with open(os.path.join(out_dir, "overall_ranking.csv"), "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["view", "arm", "avg_rank", "avg_normalized_score", "first_places", "wins",
                     "unique_avg_rank", "unique_total", "unique_avg_normalized"])
        for v in res["views"]:
            for a in v.get("avg_rank", {}):
                wr.writerow([v["view"], a, v["avg_rank"][a], v["avg_normalized"][a], v["first_places"][a],
                             v["wins"][a], v["unique_avg_rank"][a], v["unique_total"][a],
                             v["unique_avg_normalized"][a]])
    with open(os.path.join(out_dir, "pairwise_tests.csv"), "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["benchmark", "arm_a", "arm_b", "p_two_sided", "p_holm", "a12", "a_better_than_b",
                     "b_better_than_a", "unique_a_not_b", "unique_b_not_a", "jaccard"])
        for r in res["per_benchmark"]:
            for (a, b), v in r["mwu"].items():
                wr.writerow([r["benchmark"], a, b, v["p"], v["p_holm"], r["a12"][(a, b)], r["better_than"][(a, b)],
                             r["better_than"][(b, a)], r["pairwise_unique"][(b, a)], r["pairwise_unique"][(a, b)],
                             r["jaccard"][(a, b)]])


def generate_statistics_report(experiment_path, out_dir, metric="branches", baseline=None, compare_to=None,
                               html=False):
    """Analyse an experiment and write index.html plus CSV tables to out_dir. Returns the HTML path.

    html: also an llvm-cov HTML source report per arm and benchmark, in out_dir/html/ (coverage_html.py).
    """
    res = analyse(experiment_path, metric, baseline)
    comparison = compare_experiments(res, analyse(compare_to, metric, baseline)) if compare_to else None
    os.makedirs(out_dir, exist_ok=True)
    write_tables(res, out_dir)
    if html:
        reports = coverage_html.html_reports(res, out_dir)
        logging.info(f"{len(reports)} HTML source report(s) in {os.path.join(out_dir, 'html')}")
    path = os.path.join(out_dir, "index.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(render_html(res, comparison))
    return path


def main():
    parser = argparse.ArgumentParser(description="Statistical analysis of an experiment's coverage, as HTML.")
    parser.add_argument("experiment_path", help="The experiment folder (<experiment_filestore>/<name>)")
    parser.add_argument("-o", "--output-dir", help="Output folder (default: <experiment_path>/statistics)")
    parser.add_argument("--metric", choices=METRICS, default="branches", help="Primary coverage metric")
    parser.add_argument("--baseline", help="Fuzzer the other fuzzers are compared against (default: aflplusplus)")
    parser.add_argument("--compare-to", help="Another experiment folder, for the reproducibility section")
    parser.add_argument("--html", action="store_true", help="Also write llvm-cov HTML source reports per arm")
    args = parser.parse_args()
    out = args.output_dir or os.path.join(args.experiment_path, "statistics")
    path = generate_statistics_report(args.experiment_path, out, args.metric, args.baseline, args.compare_to,
                                      args.html)
    logging.info(f"Statistics report written to {path}")


if __name__ == "__main__":
    main()
