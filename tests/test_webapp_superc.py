"""The web app's Presence conditions tab, on a report written by common/superc.py itself."""
import os
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "common"))
sys.path.insert(0, os.path.join(ROOT, "webapp"))

import superc
import superc_view

# Two arms on one build: A covers lines of JIT and UNICODE, B of UNICODE and WIN32; nobody covers DEBUG.
PCS = {("defined SUPPORT_JIT", "/s/a.c"): {1, 2, 3}, ("defined SUPPORT_UNICODE", "/s/a.c"): {4, 5},
       ("defined _WIN32", "/s/b.c"): {1, 2}, ("defined DEBUG", "/s/b.c"): {3, 4}, ("1", "/s/b.c"): {5}}
COVERAGE = {
    "A": {"/s/a.c": ({1, 2, 3, 4, 5}, {1, 4}), "/s/b.c": ({1, 2, 3, 4, 5}, {5})},
    "B": {"/s/a.c": ({1, 2, 3, 4, 5}, {5}), "/s/b.c": ({1, 2, 3, 4, 5}, {2, 5}), "/s/h.h": ({9}, {9})},
}


def make_report(tmp_path):
    exp, rep = tmp_path / "exp" / "e1", tmp_path / "rep" / "e1" / "superc"
    rep.mkdir(parents=True)
    summaries = {a: superc.summarize(PCS, cov) for a, cov in COVERAGE.items()}
    results = [("xz_xz", "default", a, 2, {**superc.coverage_counts(summaries[a]), **superc.unassigned(PCS, COVERAGE[a])},
                [superc.coverage_counts(summaries[a])] * 2, 3, 2) for a in sorted(COVERAGE)]
    superc.write_report(results, {("xz_xz", "default"): (sorted(COVERAGE), summaries)}, str(rep), str(exp))
    status = exp / "superc" / "cts_default_xz_xz_0"
    status.mkdir(parents=True)
    (status / "status.tsv").write_text("/s/a.c\t0\t12\n/s/b.c\t0\t8\n/s/c.c\t124\t600\n")
    return {"experiment_filestore": str(tmp_path / "exp"), "report_filestore": str(tmp_path / "rep")}


def test_overview(tmp_path):
    cfg = make_report(tmp_path)
    assert superc_view.has_report(cfg, "e1") and not superc_view.has_report(cfg, "missing")
    data = superc_view.overview(cfg, "e1")
    (b,) = data["builds"]
    assert b["key"] == "xz_xz" and b["arms"] == ["A", "B"]
    rows = {r["arm"]: r for r in b["rows"]}
    assert rows["A"]["conditions_covered_union"] == 2 and rows["B"]["conditions_covered_union"] == 2
    assert b["only"] == {"A": 1, "B": 1}          # JIT only by A, WIN32 only by B
    assert (b["in_build"], b["uncovered"]) == (4, 1)  # DEBUG is in the build, nobody covered it
    assert rows["B"]["covered_lines_in_headers"] == 1
    st = b["superc"]
    assert (st["files"], st["ok"], st["timed_out"], st["failed"]) == (3, 2, 1, 0)
    assert st["problems"] == [{"file": "/s/c.c", "code": 124, "seconds": 600, "reason": "timed out"}]
    assert "pc_summary.csv" in data["files"] and "xz_xz_pc_comparison.csv" in data["files"]


def test_conditions_filters(tmp_path):
    cfg = make_report(tmp_path)
    names = lambda **kw: [r["condition"] for r in superc_view.conditions(cfg, "e1", "xz_xz", **kw)["rows"]]
    assert sorted(names(show="in_build")) == ["defined DEBUG", "defined SUPPORT_JIT", "defined SUPPORT_UNICODE", "defined _WIN32"]
    assert names(show="uncovered") == ["defined DEBUG"]
    assert names(show="only", arm="A") == ["defined SUPPORT_JIT"]
    assert names(show="missed", arm="A") == ["defined _WIN32"]
    assert names(show="only", arm="nobody") == []                   # an unknown arm matches nothing
    assert names(show="in_build", query="unicode") == ["defined SUPPORT_UNICODE"]
    assert names(show="in_build", sort="condition")[0] == "defined DEBUG"
    page = superc_view.conditions(cfg, "e1", "xz_xz", show="in_build", offset=1, limit=2)
    assert (page["matching"], page["offset"], len(page["rows"])) == (4, 1, 2)
    row = superc_view.conditions(cfg, "e1", "xz_xz", query="JIT")["rows"][0]
    assert row["lines"] == {"A": 1, "B": 0} and row["instrumented"] == 3 and row["only"] == "A"
    assert superc_view.conditions(cfg, "e1", "nope") is None


def test_api_routes(tmp_path, monkeypatch):
    import app as webapp
    import jobs as jobs_mod
    from color_logger import get_logger
    cfg = make_report(tmp_path)
    cfg.update(trials=1, max_total_time=60, cores_to_use=1)
    monkeypatch.setattr(webapp, "external_processes", lambda *a, **k: [])
    monkeypatch.setattr(webapp, "system_checks", lambda: [])
    webapp.STATE.update(config=cfg, config_path="config.yaml", token=None,
                        jobs=jobs_mod.Jobs(str(tmp_path / "jobs.db"), ROOT, cfg, get_logger("test")))
    client = webapp.app.test_client()
    r = client.get("/api/experiments/e1/superc").get_json()
    assert r["ok"] and r["builds"][0]["only"] == {"A": 1, "B": 1}
    r = client.get("/api/experiments/e1/superc/xz_xz/conditions?show=only&arm=B").get_json()
    assert [x["condition"] for x in r["rows"]] == ["defined _WIN32"]
    assert client.get("/api/experiments/e1/superc/..%2Fx/conditions").status_code == 404
    assert client.get("/api/experiments/e1/superc/nope/conditions").status_code == 404
    assert client.get("/api/experiments/other/superc").get_json()["ok"] is False
    page = client.get("/experiments/e1")
    assert page.status_code == 200 and b'data-tab="superc"' in page.data
