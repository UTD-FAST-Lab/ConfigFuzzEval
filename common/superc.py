"""SuperC presence-condition analysis: which #if conditions the fuzzers' coverage reached.

SuperC (cfg-analysis/, image fbpp/superc_runner:<version>) parses a benchmark's C
files with every configuration at once and gives each source line its presence
condition: the #if/#ifdef condition under which the line is compiled ("1" when it
always is). This joins those conditions with the trials' line coverage:

  1. once per benchmark build (the copy 0 of each compile-time strategy), SuperC runs on
     the .c files of the build's coverage report, with the sources of that coverage
     build (the experiment's own copy in benchmarks/coverage_<copy>/source, or the
     coverage image), in parallel with a time limit per file;
  2. for every trial, each presence condition gets the build's instrumented lines under
     it (the lines LCOV lists) and those the trial covered;
  3. per benchmark, the arms (fuzzer[runtime strategy], as in the statistics report) are
     compared by the conditions their trials covered together.

Lines are keyed by their absolute path in the coverage build, as in the LCOV reports,
so files with the same name in different folders are kept apart.

Outputs:
  <experiment>/superc/<copy>/         pc/ (SuperC's trees), logs/, status.tsv, files.txt
  <experiment>/data/<trial>/pc_analysis/pc_coverage_summary.{json,csv}
  <report>/superc/index.html          per benchmark and arm, with
  <report>/superc/pc_summary.csv      covered conditions per arm and benchmark, and
  <report>/superc/<benchmark>_pc_comparison.csv  every condition with the arms that covered it

Run at the end of an experiment (unless no_superc), or on a finished one with
    python3 common/post_analysis.py --state <experiment>/experiment_state.pkl --superc
or  python3 common/superc.py EXPERIMENT_PATH [-o OUT_DIR] [--jobs N] [--timeout S]
"""
import argparse
import csv
import hashlib
import html
import json
import os
import re
import subprocess
import time
from collections import Counter, defaultdict

from color_logger import get_logger

logging = get_logger(__name__)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SUPERC_DIR = os.path.join(PROJECT_ROOT, "cfg-analysis")
ALWAYS = "1"            # the presence condition of unconditional code
NEVER = "0"             # of code no configuration compiles (#if 0, or contradicting conditions)
EXCLUDES = ["*.o", "*.a", "*.so", "*.so.*", "*.lo", "*.la", ".git", "*.profraw", "*.profdata"]


# --- The SuperC image ---------------------------------------------------------------

def image_name():
    """fbpp/superc_runner:<hash of cfg-analysis/>, so a changed Dockerfile or script is rebuilt."""
    digest = hashlib.sha256()
    for name in ("Dockerfile", "run_superc.sh"):
        with open(os.path.join(SUPERC_DIR, name), "rb") as f:
            digest.update(f.read())
    return f"fbpp/superc_runner:{digest.hexdigest()[:12]}"


def build_image(log_file):
    """Builds the SuperC image unless it exists. Returns True when it is there."""
    image = image_name()
    if subprocess.run(["docker", "image", "inspect", image], capture_output=True).returncode == 0:
        logging.info(f"SuperC image {image} exists")
        return True
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    with open(log_file, "w") as log:
        result = subprocess.run(["docker", "build", "-t", image, SUPERC_DIR], stdout=log, stderr=subprocess.STDOUT)
    if result.returncode != 0:
        logging.error(f"Building {image} failed; see {log_file}")
        return False
    logging.success(f"Built {image}")
    return True


# --- Coverage reports -----------------------------------------------------------------

def parse_lcov(path):
    """{absolute file: (instrumented lines, covered lines)} of an LCOV report."""
    files = {}
    current = None
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.startswith("SF:"):
                current = files.setdefault(line[3:].rstrip("\n"), (set(), set()))
            elif line.startswith("DA:") and current is not None:
                parts = line[3:].rstrip("\n").split(",")
                if len(parts) >= 2:
                    number = int(parts[0])
                    current[0].add(number)
                    if parts[1] not in ("0", "-"):
                        current[1].add(number)
    return files


def source_root(paths):
    """The top folder most of the coverage build's files are in, as /<name>."""
    tops = Counter(p.split("/")[1] for p in paths if p.startswith("/") and p.count("/") >= 2)
    if not tops:
        raise ValueError("no absolute source paths in the coverage report")
    return "/" + tops.most_common(1)[0][0]


def read_flags(benchmark, root):
    """[(option, value)] from benchmarks/<benchmark>/superc_flags.txt, the build's flags:
    "-I <dir>" relative to the source root (made absolute) and "-D NAME[=VALUE]".
    Without the file, or without any -I in it, the source root is the include directory."""
    path = os.path.join(PROJECT_ROOT, "benchmarks", benchmark, "superc_flags.txt")
    flags = []
    if os.path.isfile(path):
        with open(path) as f:
            for number, line in enumerate(f, 1):
                line = line.split("#", 1)[0].strip()
                if not line:
                    continue
                option, _, value = line.partition(" ")
                value = value.strip()
                if option not in ("-I", "-D") or not value or " " in value:
                    raise ValueError(f"{os.path.relpath(path, PROJECT_ROOT)}:{number}: expected "
                                     f"'-I <dir>' or '-D NAME[=VALUE]', got {line!r}")
                flags.append((option, os.path.normpath(os.path.join(root, value)) if option == "-I" else value))
    else:
        logging.warning(f"No {os.path.relpath(path, PROJECT_ROOT)}: SuperC uses only {root} for includes")
    if not any(option == "-I" for option, _ in flags):
        flags.insert(0, ("-I", root))
    return flags


# --- Sources of a coverage build ------------------------------------------------------

_sources = {}


def prepare_sources(experiment_path, cts_benchmark, root, dest):
    """See _prepare_sources; found once per coverage build."""
    key = (os.path.abspath(experiment_path), cts_benchmark)
    if key not in _sources:
        _sources[key] = _prepare_sources(experiment_path, cts_benchmark, root, dest)
    return _sources[key]


def _prepare_sources(experiment_path, cts_benchmark, root, dest):
    """The source tree of a coverage build at dest (absolute paths under root map to dest).

    In order: an earlier copy at dest; the experiment's own copy in
    benchmarks/coverage_<copy>/source (made by the benchmark's build, so it matches
    the coverage exactly); the coverage image fbpp/benchmark:coverage_<copy>, which
    matches as long as the image was not rebuilt since the experiment.
    """
    if os.path.isdir(dest) and os.listdir(dest):
        return dest
    own = os.path.join(experiment_path, "benchmarks", f"coverage_{cts_benchmark}", "source")
    if os.path.isdir(own) and os.listdir(own):
        logging.info(f"SuperC sources of {cts_benchmark}: the experiment's copy {own}")
        return own
    image = f"fbpp/benchmark:coverage_{cts_benchmark}"
    logging.info(f"SuperC sources of {cts_benchmark}: {root} from {image}")
    os.makedirs(dest, exist_ok=True)
    pack = subprocess.Popen(["docker", "run", "--rm", "--entrypoint", "tar", image, "-C", root,
                             *[f"--exclude={e}" for e in EXCLUDES], "-cf", "-", "."],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    unpack = subprocess.run(["tar", "-x", "-C", dest], stdin=pack.stdout, capture_output=True)
    pack.stdout.close()
    error = pack.stderr.read().decode(errors="replace")
    pack.wait()
    if pack.returncode != 0 or unpack.returncode != 0 or not os.listdir(dest):
        raise RuntimeError(f"cannot copy {root} out of {image}: {(error + unpack.stderr.decode())[-500:]}")
    return dest


# --- Running SuperC -------------------------------------------------------------------

def run_superc(experiment_path, cts_benchmark, benchmark, source_files, cores, memory_gb=None,
               timeout=600, heap="2g"):
    """SuperC on |source_files| (absolute .c paths of one coverage build).

    Returns the output folder (<experiment>/superc/<copy>), with pc/<path>.json per
    analysed file. A file analysed before (with status 0) is not analysed again.
    """
    out = os.path.join(experiment_path, "superc", cts_benchmark)
    os.makedirs(out, exist_ok=True)
    root = source_root(source_files)
    src = prepare_sources(experiment_path, cts_benchmark, root, os.path.join(out, "source"))
    done = set()
    status_path = os.path.join(out, "status.tsv")
    if os.path.isfile(status_path):
        with open(status_path) as f:
            done = {r[0] for r in csv.reader(f, delimiter="\t") if len(r) >= 2 and r[1] == "0"}
    todo = [p for p in sorted(source_files) if p not in done and os.path.isfile(os.path.join(src, os.path.relpath(p, root)))]
    missing = [p for p in source_files if not os.path.isfile(os.path.join(src, os.path.relpath(p, root)))]
    if missing:
        logging.warning(f"SuperC: {len(missing)} file(s) of {cts_benchmark} are not in its sources, "
                        f"for example {missing[0]}")
    with open(os.path.join(out, "files.txt"), "w") as f:
        f.write("".join(p + "\n" for p in todo))
    with open(os.path.join(out, "flags.txt"), "w") as f:
        f.write("".join(f"{option} {value}\n" for option, value in read_flags(benchmark, root)))
    if not todo:
        return out
    previous = open(status_path).read() if done else ""
    jobs = max(1, len(cores))
    command = ["docker", "run", "--rm", "--label", f"fbpp.experiment={os.path.basename(os.path.normpath(experiment_path))}",
               # As this user, so its output can be removed and redone without root.
               "--user", f"{os.getuid()}:{os.getgid()}",
               f"--cpuset-cpus={','.join(map(str, cores))}", "-e", f"SUPERC_JOBS={jobs}",
               "-e", f"SUPERC_TIMEOUT={timeout}", "-e", f"SUPERC_HEAP={heap}",
               "-v", f"{os.path.abspath(src)}:{root}:ro", "-v", f"{os.path.abspath(out)}:/out"]
    if memory_gb:
        command += ["-m", f"{memory_gb}g", f"--memory-swap={memory_gb}g"]
    started = time.time()
    with open(os.path.join(out, "superc.log"), "a") as log:
        result = subprocess.run(command + [image_name()], stdout=log, stderr=subprocess.STDOUT)
    if previous:                      # the container started status.tsv again: keep the earlier files
        with open(status_path) as f:
            new = f.read()
        with open(status_path, "w") as f:
            f.write(previous + new)
    logging.info(f"SuperC on {len(todo)} file(s) of {cts_benchmark} took {time.time() - started:.0f} s "
                 f"(exit code {result.returncode}; {os.path.relpath(status_path, experiment_path)})")
    return out


def superc_status(out):
    """{file: (exit code, seconds)} from status.tsv; the last line of a file wins."""
    status = {}
    path = os.path.join(out, "status.tsv")
    if os.path.isfile(path):
        with open(path) as f:
            for row in csv.reader(f, delimiter="\t"):
                if len(row) == 3:
                    status[row[0]] = (int(row[1]), int(row[2]))
    return status


# --- Presence conditions --------------------------------------------------------------

def _children(node):
    for sub in node.get("Sub", []) or []:
        for item in (sub if isinstance(sub, list) else [sub]):
            if isinstance(item, dict):
                yield item


def _tokens(text):
    i = 0
    while i < len(text):
        c = text[i]
        if c.isspace():
            i += 1
        elif c in "()":
            yield c
            i += 1
        elif c == "|":
            j = text.index("|", i + 1)
            yield text[i:j + 1]
            i = j + 1
        else:
            j = i
            while j < len(text) and not text[j].isspace() and text[j] not in "()|":
                j += 1
            yield text[i:j]
            i = j


def _parse_all(text):
    """The s-expressions of |text|, as nested lists of atoms."""
    tokens = list(_tokens(text))
    out, stack = [], []
    for token in tokens:
        if token == "(":
            stack.append([])
        elif token == ")":
            if not stack:
                raise ValueError("unbalanced parentheses")
            done = stack.pop()
            (stack[-1] if stack else out).append(done)
        else:
            (stack[-1] if stack else out).append(token)
    if stack:
        raise ValueError("unbalanced parentheses")
    return out


def _to_c(expr):
    """A C-style condition from an SMT-LIB expression: "1" true, "0" false."""
    if isinstance(expr, str):
        if expr in ("and", "true"):
            return ALWAYS
        if expr in ("or", "false"):
            return NEVER
        name = expr.strip("|")
        if name.startswith("(defined ") and name.endswith(")"):
            return f"defined({name[len('(defined '):-1].strip()})"
        return name
    op, args = expr[0], [_to_c(a) for a in expr[1:]]
    if op == "not":
        inner = args[0]
        return NEVER if inner == ALWAYS else ALWAYS if inner == NEVER else (
            f"!{inner}" if inner.replace("_", "").replace("(", "").replace(")", "").isalnum() else f"!({inner})")
    if op == "and":
        if NEVER in args:
            return NEVER
        args = list(dict.fromkeys(a for a in args if a != ALWAYS))
        if len(args) == 1:
            return args[0]
        return ALWAYS if not args else " && ".join(a if " || " not in a else f"({a})" for a in args)
    if op == "or":
        if ALWAYS in args:
            return ALWAYS
        args = list(dict.fromkeys(a for a in args if a != NEVER))
        if len(args) == 1:
            return args[0]
        return NEVER if not args else " || ".join(a if " && " not in a else f"({a})" for a in args)
    raise ValueError(f"unknown operator {op}")


def condition(pc):
    """SuperC's presence condition (SMT-LIB declare-fun lines and one assert) as a C-style
    expression, for example defined(HAVE_X) && !FOO; "1" always, "0" never."""
    text = str(pc or "").strip()
    if not text:
        return ALWAYS
    asserts = [e for e in _parse_all(text) if isinstance(e, list) and e and e[0] == "assert"]
    if not asserts:
        return " ".join(text.split())
    return _to_c(["and", *[a[1] for a in asserts]])


def pc_lines(tree):
    """{presence condition: set of line numbers} of a SuperC -sourcelinePC tree. Each region
    has its full condition; a line belongs to the innermost region that contains it."""
    lines = defaultdict(set)

    def walk(node):
        start, end = node.get("StartLine", 0), node.get("EndLine", -1)
        own = set(range(start, end + 1)) if isinstance(start, int) and isinstance(end, int) and end >= start else set()
        inner = set()
        for child in _children(node):
            inner |= walk(child)
        lines[condition(node.get("PC", ""))] |= own - inner
        return own | inner

    walk(tree)
    return {pc: ls for pc, ls in lines.items() if ls}


def strip_comments(text):
    """|text| with C comments blanked (newlines kept, so line numbers stay), outside strings."""
    out, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        if c == "/" and text.startswith("/*", i):
            end = text.find("*/", i + 2)
            end = n if end < 0 else end + 2
            out.append("".join(ch if ch == "\n" else " " for ch in text[i:end]))
            i = end
        elif c == "/" and text.startswith("//", i):
            end = text.find("\n", i)
            end = n if end < 0 else end
            out.append(" " * (end - i))
            i = end
        elif c in "\"'":
            j = i + 1
            while j < n and text[j] != c and text[j] != "\n":
                j += 2 if text[j] == "\\" else 1
            out.append(text[i:j + 1])
            i = j + 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


CONDITIONAL_DIRECTIVE = re.compile(r"^\s*#\s*(if|ifdef|ifndef|elif|elifdef|elifndef|else|endif)\b")


def extend_tree(tree, source_path):
    """The top region of |tree| over the whole file, up to any #if block SuperC did not report.

    SuperC's top region often ends early (at line 1 for a file without #if, or before a
    block it does report), so its EndLine says nothing. Every line outside the inner regions
    is top-level code, under the top region's condition, unless a conditional directive there
    is in no inner region: then SuperC stopped early, and the top region ends before it.
    Returns (tree, True) when SuperC stopped early."""
    try:
        with open(source_path, errors="replace") as f:
            lines = strip_comments(f.read()).split("\n")
    except OSError:
        return tree, False
    covered = []

    def inner(node):
        for child in _children(node):
            start, end = child.get("StartLine", 0), child.get("EndLine", -1)
            if isinstance(start, int) and isinstance(end, int) and end >= start:
                covered.append((start, end))
            inner(child)

    inner(tree)
    missed = [n for n, line in enumerate(lines, 1) if CONDITIONAL_DIRECTIVE.match(line)
              and not any(start <= n <= end for start, end in covered)]
    end = missed[0] - 1 if missed else len(lines)
    return {**tree, "StartLine": min(tree.get("StartLine", 0), 0), "EndLine": end}, bool(missed)


def load_pcs(out, src=None, root=None):
    """{(presence condition, file): lines} for every file SuperC analysed in |out|.

    With the sources (src holding root), a tree SuperC ended early is extended where that is
    safe (extend_tree); the files whose trees still stop early are in load_pcs.stopped_early."""
    pcs = {}
    stopped = load_pcs.stopped_early = []
    pc_dir = os.path.join(out, "pc")
    for dirpath, _, names in os.walk(pc_dir):
        for name in names:
            if not name.endswith(".json"):
                continue
            path = os.path.join(dirpath, name)
            source = "/" + os.path.relpath(path, pc_dir)[:-len(".json")]
            try:
                with open(path) as f:
                    tree = json.load(f)
            except (OSError, ValueError) as e:
                logging.warning(f"SuperC output {path} is not readable: {e}")
                continue
            if src is not None:
                tree, early = extend_tree(tree, os.path.join(src, os.path.relpath(source, root)))
                if early:
                    stopped.append((source, tree.get("EndLine") + 1))
            for pc, lines in pc_lines(tree).items():
                pcs[(pc, source)] = lines
    return pcs


def summarize(pcs, lcov_files):
    """Per presence condition: files, lines in the source, lines the build instrumented and
    lines covered, from {(pc, file): lines} and {file: (instrumented, covered)}."""
    summary = {}
    for (pc, source), lines in pcs.items():
        instrumented, covered = lcov_files.get(source, (set(), set()))
        s = summary.setdefault(pc, {"files": set(), "source_lines": 0, "instrumented_lines": 0, "covered_lines": 0})
        s["files"].add(source)
        s["source_lines"] += len(lines)
        s["instrumented_lines"] += len(lines & instrumented)
        s["covered_lines"] += len(lines & covered)
    return summary


def coverage_counts(summary):
    """Totals over the conditional code (every condition but "1" and "0")."""
    conditional = {pc: s for pc, s in summary.items() if pc not in (ALWAYS, NEVER)}
    built = {pc: s for pc, s in conditional.items() if s["instrumented_lines"]}
    covered = {pc: s for pc, s in built.items() if s["covered_lines"]}
    return {"conditions": len(conditional), "conditions_in_build": len(built), "conditions_covered": len(covered),
            "conditional_lines_in_build": sum(s["instrumented_lines"] for s in built.values()),
            "conditional_lines_covered": sum(s["covered_lines"] for s in built.values())}


def unassigned(pcs, lcov_files):
    """Covered lines that have no presence condition: in headers (SuperC gives conditions for
    the lines of the .c file it parses only) and in .c files past where SuperC's tree ends."""
    assigned = defaultdict(set)
    for (_, source), lines in pcs.items():
        assigned[source] |= lines
    counts = {"covered_lines": 0, "covered_lines_in_headers": 0, "covered_lines_without_condition": 0}
    for source, (_, covered) in lcov_files.items():
        counts["covered_lines"] += len(covered)
        if not source.endswith(".c"):
            counts["covered_lines_in_headers"] += len(covered)
        else:
            counts["covered_lines_without_condition"] += len(covered - assigned.get(source, set()))
    return counts


def write_summary(summary, path_json, path_csv):
    with open(path_json, "w") as f:
        json.dump({pc: {**s, "files": sorted(s["files"])} for pc, s in summary.items()}, f, indent=1)
    with open(path_csv, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["presence_condition", "files", "source_lines", "instrumented_lines", "covered_lines"])
        for pc, s in sorted(summary.items(), key=lambda kv: (-kv[1]["instrumented_lines"], kv[0])):
            # The file list is in the JSON; for "1" it is nearly every file, too long for a CSV field.
            writer.writerow([pc, len(s["files"]), s["source_lines"], s["instrumented_lines"], s["covered_lines"]])


# --- An experiment ----------------------------------------------------------------------

def lcov_reports(trial_dir):
    """The trial's LCOV reports: lcov_results/ (every copy of a compile-time strategy, gathered
    by run_experiment.aggregate_results) or coverage/report.json."""
    gathered = os.path.join(trial_dir, "lcov_results")
    if os.path.isdir(gathered) and os.listdir(gathered):
        return sorted(os.path.join(gathered, f) for f in os.listdir(gathered))
    own = os.path.join(trial_dir, "coverage", "report.json")
    return [own] if os.path.isfile(own) else []


def merged_lcov(paths):
    files = {}
    for path in paths:
        for source, (instrumented, covered) in parse_lcov(path).items():
            i, c = files.setdefault(source, (set(), set()))
            i |= instrumented
            c |= covered
    return files


def experiment_trials(experiment_path):
    """[(arm, fuzzer, rts, cts, benchmark, trial, trial dir)] of copy 0 of every trial with coverage."""
    from statistical_analysis import arm_name, trial_identity
    trials = []
    data = os.path.join(experiment_path, "data")
    for entry in sorted(os.listdir(data)):
        trial_dir = os.path.join(data, entry)
        if not os.path.isdir(trial_dir):
            continue
        ident = trial_identity(entry, trial_dir)
        if ident is None or ident["copy"] != 0 or not lcov_reports(trial_dir):
            continue
        trials.append((arm_name(ident["fuzzer"], ident["rts"], ident["cts"]), ident["fuzzer"], ident["rts"],
                       ident["cts"], ident["benchmark"], ident["trial"], trial_dir))
    return trials


def analyse_experiment(experiment_path, report_dir, cores, memory_gb=None, timeout=600, heap="2g"):
    """SuperC on every benchmark build of the experiment, then every trial and the arms
    per benchmark. Returns the report's index.html, or None without trials."""
    trials = experiment_trials(experiment_path)
    if not trials:
        logging.warning(f"SuperC: no trial with a coverage report in {experiment_path}/data")
        return None
    by_build = defaultdict(list)
    for t in trials:
        by_build[(t[3], t[4])].append(t)

    results = []          # (benchmark, cts, arm, trials, counts of the arm's union, per-trial counts)
    comparisons = {}
    for (cts, benchmark), build_trials in sorted(by_build.items()):
        cts_benchmark = f"cts_{cts}_{benchmark}_0"
        coverage = {t[6]: merged_lcov(lcov_reports(t[6])) for t in build_trials}
        files = sorted({f for cov in coverage.values() for f in cov if f.endswith(".c")})
        try:
            out = run_superc(experiment_path, cts_benchmark, benchmark, files, cores, memory_gb, timeout, heap)
        except (RuntimeError, ValueError, OSError) as e:
            logging.error(f"SuperC on {cts_benchmark} failed: {e}")
            continue
        status = superc_status(out)
        bad = [f for f in files if status.get(f, (None,))[0] not in (0,)]
        if bad:
            logging.warning(f"SuperC: {len(bad)} of {len(files)} file(s) of {cts_benchmark} have no result "
                            f"(timed out or failed; see {os.path.relpath(out, experiment_path)}/status.tsv)")
        root = source_root(files)
        pcs = load_pcs(out, prepare_sources(experiment_path, cts_benchmark, root, os.path.join(out, "source")), root)
        if load_pcs.stopped_early:
            logging.warning(f"SuperC: {len(load_pcs.stopped_early)} file(s) of {cts_benchmark} have an #if block "
                            f"SuperC did not report, so their lines from it on have no presence condition: "
                            f"{', '.join(f'{s} (line {e})' for s, e in load_pcs.stopped_early[:5])}"
                            + (" ..." if len(load_pcs.stopped_early) > 5 else ""))

        arm_union = defaultdict(dict)
        arm_trial_counts = defaultdict(list)
        for t in build_trials:
            arm, trial_dir = t[0], t[6]
            summary = summarize(pcs, coverage[trial_dir])
            pc_dir = os.path.join(trial_dir, "pc_analysis")
            os.makedirs(pc_dir, exist_ok=True)
            write_summary(summary, os.path.join(pc_dir, "pc_coverage_summary.json"),
                          os.path.join(pc_dir, "pc_coverage_summary.csv"))
            arm_trial_counts[arm].append(coverage_counts(summary))
            for source, (instrumented, covered) in coverage[trial_dir].items():
                i, c = arm_union[arm].setdefault(source, (set(), set()))
                i |= instrumented
                c |= covered
        arms = sorted(arm_union)
        arm_summaries = {arm: summarize(pcs, arm_union[arm]) for arm in arms}
        for arm in arms:
            results.append((benchmark, cts, arm, len(arm_trial_counts[arm]),
                            {**coverage_counts(arm_summaries[arm]), **unassigned(pcs, arm_union[arm])},
                            arm_trial_counts[arm], len(files), len(files) - len(bad)))
        comparisons[(benchmark, cts)] = (arms, arm_summaries)

    os.makedirs(report_dir, exist_ok=True)
    write_report(results, comparisons, report_dir, experiment_path)
    return os.path.join(report_dir, "index.html")


def _median(values):
    values = sorted(values)
    n = len(values)
    return (values[n // 2] if n % 2 else (values[n // 2 - 1] + values[n // 2]) / 2) if n else 0


def write_report(results, comparisons, report_dir, experiment_path):
    with open(os.path.join(report_dir, "pc_summary.csv"), "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["benchmark", "compiletime", "arm", "trials", "files", "files_analysed", "conditions",
                         "conditions_in_build", "conditions_covered_union", "conditions_covered_median_trial",
                         "conditional_lines_in_build", "conditional_lines_covered_union", "covered_lines_union",
                         "covered_lines_in_headers", "covered_lines_without_condition"])
        for benchmark, cts, arm, n, union, per_trial, files, analysed in results:
            writer.writerow([benchmark, cts, arm, n, files, analysed, union["conditions"], union["conditions_in_build"],
                             union["conditions_covered"], _median([c["conditions_covered"] for c in per_trial]),
                             union["conditional_lines_in_build"], union["conditional_lines_covered"],
                             union["covered_lines"], union["covered_lines_in_headers"],
                             union["covered_lines_without_condition"]])
    for (benchmark, cts), (arms, summaries) in comparisons.items():
        name = benchmark if cts == "default" else f"{benchmark}_cts_{cts}"
        all_pcs = sorted({pc for s in summaries.values() for pc in s if pc not in (ALWAYS, NEVER)})
        with open(os.path.join(report_dir, f"{name}_pc_comparison.csv"), "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["presence_condition", "instrumented_lines", "covered_by", "covered_only_by"]
                            + [f"covered_lines:{a}" for a in arms])
            for pc in all_pcs:
                instrumented = max(summaries[a].get(pc, {}).get("instrumented_lines", 0) for a in arms)
                lines = [summaries[a].get(pc, {}).get("covered_lines", 0) for a in arms]
                by = [a for a, n in zip(arms, lines) if n]
                writer.writerow([pc, instrumented, ";".join(by), by[0] if len(by) == 1 else ""] + lines)

    e = html.escape
    rows = "".join(
        f"<tr><td>{e(b)}</td><td>{e(c)}</td><td>{e(a)}</td><td>{n}</td><td>{an}/{fl}</td><td>{u['conditions_in_build']:,}</td>"
        f"<td>{u['conditions_covered']:,}</td><td>{_median([x['conditions_covered'] for x in pt]):,}</td>"
        f"<td>{u['conditional_lines_covered']:,} / {u['conditional_lines_in_build']:,}</td>"
        f"<td>{u['covered_lines_in_headers'] + u['covered_lines_without_condition']:,} / {u['covered_lines']:,}</td></tr>"
        for b, c, a, n, u, pt, fl, an in results)
    unique_rows = ""
    for (benchmark, cts), (arms, summaries) in comparisons.items():
        owners = Counter()
        for pc in {pc for s in summaries.values() for pc in s if pc not in (ALWAYS, NEVER)}:
            by = [a for a in arms if summaries[a].get(pc, {}).get("covered_lines", 0)]
            if len(by) == 1:
                owners[by[0]] += 1
        unique_rows += "".join(f"<tr><td>{e(benchmark)}</td><td>{e(cts)}</td><td>{e(a)}</td><td>{owners.get(a, 0):,}</td></tr>"
                               for a in arms)
    with open(os.path.join(report_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write(f"""<!doctype html><meta charset="utf-8"><title>SuperC presence conditions</title>
<style>body{{font:14px system-ui,sans-serif;margin:24px;max-width:1100px}}table{{border-collapse:collapse;margin:12px 0}}
td,th{{border:1px solid #ccc;padding:4px 8px;text-align:right}}td:nth-child(-n+3),th{{text-align:left}}</style>
<h1>Presence-condition coverage: {e(os.path.basename(os.path.normpath(experiment_path)))}</h1>
<p>SuperC gives every source line the #if condition under which it is compiled. A condition is <i>in the build</i>
when the coverage build instrumented at least one of its lines, and <i>covered</i> when a trial executed one.
Unconditional code (condition 1) and code no configuration compiles (condition 0) are left out. The union is over an arm's trials; the median is per trial.
Files: those of the coverage report that SuperC analysed, out of all its .c files.</p>
<table><tr><th>Benchmark</th><th>Compile-time</th><th>Arm</th><th>Trials</th><th>Files</th><th>Conditions in build</th>
<th>Covered (union)</th><th>Covered (median trial)</th><th>Conditional lines covered / in build</th>
<th>Covered lines without a condition / all covered</th></tr>{rows}</table>
<p><i>Covered lines without a condition</i> are in headers (SuperC gives conditions only for the lines of the
.c file it parses, so code in headers such as bfd's coffcode.h is not attributed) or in .c files past the line
where SuperC's tree ends (the experiment log names those files). They are left out of every count above.</p>
<h2>Conditions only one arm covered</h2>
<table><tr><th>Benchmark</th><th>Compile-time</th><th>Arm</th><th>Conditions</th></tr>{unique_rows}</table>
<p>Tables: <a href="pc_summary.csv">pc_summary.csv</a>, and per benchmark <code>&lt;benchmark&gt;_pc_comparison.csv</code>
with every condition, the arms that covered it and their covered lines. Per trial:
<code>data/&lt;trial&gt;/pc_analysis/pc_coverage_summary.csv</code>.</p>
""")


def main():
    parser = argparse.ArgumentParser(description="SuperC presence-condition coverage of an experiment.")
    parser.add_argument("experiment_path")
    parser.add_argument("-o", "--output-dir", help="Report folder (default: <experiment>/superc/report)")
    parser.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) - 1), help="Files at a time")
    parser.add_argument("--timeout", type=int, default=600, help="Seconds per file (default 600)")
    parser.add_argument("--heap", default="2g", help="JVM heap per file (default 2g)")
    args = parser.parse_args()
    if not build_image(os.path.join(args.experiment_path, "superc", "superc_build.log")):
        raise SystemExit(1)
    out = args.output_dir or os.path.join(args.experiment_path, "superc", "report")
    cores = list(range(os.cpu_count() - args.jobs, os.cpu_count())) if args.jobs < os.cpu_count() else list(range(os.cpu_count()))
    path = analyse_experiment(args.experiment_path, out, cores, timeout=args.timeout, heap=args.heap)
    if path:
        logging.info(f"SuperC report written to {path}")


if __name__ == "__main__":
    main()
