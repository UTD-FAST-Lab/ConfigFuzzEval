"""llvm-cov HTML source reports for the statistics report (statistical_analysis.py --html,
post_analysis.py --stats-html), as FuzzBench's coverage reports.

For every arm and benchmark, the arm's trial profiles are merged and llvm-cov show writes a
browsable report to <statistics>/html/<benchmark>/<arm>/index.html. Only the source files the
coverage build uses are copied out of its Docker image, into <statistics>/html/src/<copy>/.
"""
import json
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
        logging.warning(f"No HTML report for {arm} on {benchmark}: its trials ran on {len(copies)} benchmark copies")
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


def html_reports(res, out_dir, jobs=None):
    """An HTML source report for every arm and benchmark; {(benchmark, arm): index.html}."""
    groups = defaultdict(list)
    for t in res["trials"]:
        groups[(t["benchmark"], t["arm"])].append(t)
    with ThreadPoolExecutor(max_workers=jobs or min(4, os.cpu_count() or 1)) as pool:
        paths = pool.map(lambda key: html_report(res["experiment_path"], out_dir, *key, groups[key]), groups)
        return {key: path for key, path in zip(groups, paths) if path}
