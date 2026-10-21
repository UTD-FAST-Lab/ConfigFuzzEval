"""The combined coverage reports of common/coverage_html.py: the mean over an arm's trials."""
import os
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "common"))

import coverage_html

LCOV = """SF:/src/a.c
FN:1,f
FN:5,g
FNDA:{f},f
FNDA:0,g
DA:1,{l1}
DA:2,{l2}
DA:5,0
BRDA:2,0,0,{b}
BRDA:2,0,1,0
end_of_record
"""


def write_trial(tmp_path, name, f, l1, l2, b):
    trial = tmp_path / name / "coverage"
    trial.mkdir(parents=True)
    (trial / "report.json").write_text(LCOV.format(f=f, l1=l1, l2=l2, b=b))
    return {"dirs": [str(tmp_path / name)], "cts_benchmarks": ["cts_default_x_0"],
            "values": {"lines": int(l1 > 0) + int(l2 > 0)}, "instrumented": {"lines": 3}}




def test_combine_mean(tmp_path):
    # Trial 0 covers lines 1 and 2 and a branch, trial 1 line 1 only.
    trials = [write_trial(tmp_path, "t0", 4, 3, 1, 2), write_trial(tmp_path, "t1", 1, 1, 0, 0)]
    per_trial = [coverage_html.trial_counts(t) for t in trials]
    assert per_trial[0]["/src/a.c"]["functions"] == {"f": 4, "g": 0}
    (entry,) = coverage_html.combine_mean(per_trial).values()
    assert (entry["lines"], entry["lines_covered"]) == (3, [2, 1])
    assert (entry["branches"], entry["branches_covered"]) == (2, [1, 0])
    assert entry["functions_covered"] == [1, 1]
    assert entry["line_hits"] == {1: (2, 2.0), 2: (1, 0.5), 5: (0, 0.0)}
    assert coverage_html.mean_sd([2, 1]) == (1.5, 0.5 ** 0.5)


def test_mean_report_without_docker(tmp_path, monkeypatch):
    trials = [write_trial(tmp_path, "t0", 4, 3, 1, 2), write_trial(tmp_path, "t1", 1, 1, 0, 0)]

    def no_docker(*a, **k):
        raise FileNotFoundError("docker")
    monkeypatch.setattr(coverage_html, "copy_sources", no_docker)
    out = tmp_path / "stats"
    path = coverage_html.mean_report("exp", str(out), "x", "fuzzer", trials)
    assert path == str(out / "html" / "mean" / "x" / "fuzzer" / "index.html")
    text = open(path).read()
    assert "mean of 2 trial(s)" in text and "1.5 ± 0.7 / 3 (50.0%)" in text
    page = open(out / "html" / "mean" / "x" / "fuzzer" / "files" / "0000.html").read()
    assert "<tr class='all'><td>1</td><td>2/2</td>" in page and "<tr class='some'><td>2</td><td>1/2</td>" in page
    assert "The source is not available" in page
    rows = open(out / "html" / "mean" / "x" / "fuzzer" / "mean_files.csv").read().splitlines()
    assert rows[1].startswith("/src/a.c,2,3,1.5,")
    assert coverage_html.mean_report("exp", str(out), "x", "none", [{"dirs": [str(tmp_path / "missing")]}]) is None


def test_union_from_lcov_without_profiles(tmp_path, monkeypatch):
    # No merged.profdata: llvm-cov cannot make the union, so it comes from the LCOV reports.
    trials = [write_trial(tmp_path, "t0", 4, 3, 0, 2), write_trial(tmp_path, "t1", 1, 0, 5, 0)]
    monkeypatch.setattr(coverage_html, "copy_sources", lambda *a, **k: False)
    out = tmp_path / "stats"
    path = coverage_html.union_report("exp", str(out), "x", "fuzzer", trials)
    assert path == str(out / "html" / "x" / "fuzzer" / "index.html")
    text = open(path).read()
    assert "union of 2 trial(s)" in text and "2 / 3 (66.7%)" in text       # lines 1 and 2, each by one trial
    page = open(out / "html" / "x" / "fuzzer" / "files" / "0000.html").read()
    assert "<tr class='some'><td>2</td><td>1/2</td><td>5</td>" in page      # the total count, not the mean
    rows = open(out / "html" / "x" / "fuzzer" / "union_files.csv").read().splitlines()
    assert rows[1] == "/src/a.c,2,3,2,2,1,2,1,0"           # g never ran
