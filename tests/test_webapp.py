import os
import sys
import time

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "common"))
sys.path.insert(0, os.path.join(ROOT, "webapp"))

import catalog
import events
import experiments
import jobs as jobs_mod
from color_logger import get_logger


def test_catalog_matches_validation_rules():
    cat = catalog.load(ROOT)
    assert "aflplusplus" in cat["fuzzers"] and cat["fuzzers"]["aflplusplus"]["runtime_strategies"]
    assert not cat["fuzzers"]["zigzagfuzz"]["runtime_strategies"]
    assert not any(b.startswith("cts_") for b in cat["benchmarks"])
    for kind in ("compiletime", "runtime"):           # only folders with a strategy.py are strategies
        assert cat[kind] and all(os.path.isfile(os.path.join(ROOT, kind, s, "strategy.py")) for s in cat[kind])
    assert catalog.problems(cat, "aflplusplus", "pcre2_pcre2test", "random") == []
    assert catalog.problems(cat, "zigzagfuzz", "pcre2_pcre2test", "random") == \
        ["zigzagfuzz does not support runtime strategies"]


def test_process_experiment_name(tmp_path):
    exp = tmp_path / "exp.yaml"
    exp.write_text("experiment_name: from_file\ngroups: []\n")
    assert jobs_mod.process_experiment_name(["python3", "x.py", "--experiment-name", "a"], "/") == "a"
    assert jobs_mod.process_experiment_name(["python3", "x.py", "--experiment", "exp.yaml"], str(tmp_path)) == "from_file"
    assert jobs_mod.process_experiment_name(["python3", "p.py", "--state", "/f/store/myexp/experiment_state.pkl"], "/") == "myexp"


def test_valid_name():
    assert experiments.valid_name("stats_test-1.2")
    assert not experiments.valid_name("../etc")
    assert not experiments.valid_name("a/b")
    assert not experiments.valid_name("")


def make_jobs(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs_mod, "external_processes", lambda *a, **k: [])
    cfg = {"experiment_filestore": str(tmp_path / "store")}
    return jobs_mod.Jobs(str(tmp_path / "db" / "jobs.db"), str(tmp_path), cfg, get_logger("test"))


def wait_for(fn, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        if fn():
            return True
        time.sleep(0.1)
    return False


def test_queue_runs_one_job_at_a_time(tmp_path, monkeypatch):
    q = make_jobs(tmp_path, monkeypatch)
    a = q.enqueue("post", "e1", "first", [sys.executable, "-c", "import time; time.sleep(1)"], str(tmp_path / "a.log"))
    b = q.enqueue("post", "e2", "second", [sys.executable, "-c", "print('hi')"], str(tmp_path / "b.log"))
    q.tick()
    assert q.get(a)["status"] == "running" and q.get(b)["status"] == "queued"
    assert wait_for(lambda: (q.tick(), q.get(a)["status"])[1] == "finished")
    assert wait_for(lambda: (q.tick(), q.get(b)["status"])[1] == "finished")
    assert q.get(b)["returncode"] == 0
    assert open(tmp_path / "b.log").read().strip() == "hi"


def test_failed_job_and_queued_cancel(tmp_path, monkeypatch):
    q = make_jobs(tmp_path, monkeypatch)
    a = q.enqueue("post", "e1", "fails", [sys.executable, "-c", "raise SystemExit(3)"], str(tmp_path / "a.log"))
    b = q.enqueue("post", "e2", "never", [sys.executable, "-c", "pass"], str(tmp_path / "b.log"))
    assert q.cancel(b) and q.get(b)["status"] == "cancelled"
    q.tick()
    assert wait_for(lambda: (q.tick(), q.get(a)["status"])[1] == "failed")
    assert q.get(a)["returncode"] == 3


def test_cancel_running_job_kills_its_process_group(tmp_path, monkeypatch):
    q = make_jobs(tmp_path, monkeypatch)
    monkeypatch.setattr(jobs_mod, "stop_containers", lambda name: None)
    # A child of the job's process must die too (the whole process group is signalled)
    child = tmp_path / "child.pid"
    code = f"import subprocess, time; p = subprocess.Popen(['sleep', '60']); open({str(child)!r}, 'w').write(str(p.pid)); time.sleep(60)"
    a = q.enqueue("post", "e1", "long", [sys.executable, "-c", code], str(tmp_path / "a.log"))
    q.tick()
    assert wait_for(lambda: child.exists() and child.read_text())
    assert q.cancel(a)
    assert wait_for(lambda: q.get(a)["status"] == "cancelled", timeout=20)
    child_pid = int(child.read_text())
    assert wait_for(lambda: (q.tick(), not jobs_mod.pid_alive(child_pid))[1])
    assert a not in q.procs                      # the job process was reaped


def test_summary_and_trials_from_events(tmp_path):
    store = tmp_path / "store"
    exp = store / "e1"
    (exp / "data").mkdir(parents=True)
    import pickle
    with open(exp / "experiment_state.pkl", "wb") as f:
        pickle.dump({"trial_tasks": [("aflplusplus", "random", "cts_default_xz_xz_0", 0, 1, None, 60),
                                     ("aflplusplus", "default", "cts_default_xz_xz_0", 0, 1, None, 60)],
                     "fuzzers": ["aflplusplus"], "benchmarks": ["xz_xz"], "runtime_strategies": ["default", "random"]}, f)
    events.emit(str(exp), "phase", phase="fuzzing")
    events.emit(str(exp), "trial_start", run="aflplusplus_rts_random", benchmark="cts_default_xz_xz_0", trial=0, core=3)
    events.emit(str(exp), "trial_end", run="aflplusplus_rts_random", benchmark="cts_default_xz_xz_0", trial=0,
                core=3, status="success")
    cfg = {"experiment_filestore": str(store), "report_filestore": str(tmp_path / "reports")}
    s = experiments.summary(cfg, "e1", running_names={"e1"})
    assert (s["status"], s["phase"], s["done"], s["planned"]) == ("running", "fuzzing", 1, 2)
    t = {x["arm"]: x for x in experiments.trials(cfg, "e1", running=True)}
    assert t["aflplusplus[random]"]["status"] == "success" and t["aflplusplus[random]"]["core"] == 3
    assert t["aflplusplus[random]"]["bench"] == "xz_xz"
    assert t["aflplusplus"]["status"] == "queued"
    events.emit(str(exp), "finished")
    assert experiments.summary(cfg, "e1")["status"] == "finished"


def test_flask_routes(tmp_path, monkeypatch):
    import app as webapp
    monkeypatch.setattr(jobs_mod, "external_processes", lambda *a, **k: [])
    monkeypatch.setattr(webapp, "external_processes", lambda *a, **k: [])
    monkeypatch.setattr(webapp, "system_checks", lambda: [])
    cfg = {"experiment_filestore": str(tmp_path / "store"), "report_filestore": str(tmp_path / "reports"),
           "trials": 1, "max_total_time": 60, "cores_to_use": 1}
    (tmp_path / "store").mkdir()
    webapp.STATE.update(config=cfg, config_path="config.yaml", token=None,
                        jobs=jobs_mod.Jobs(str(tmp_path / "jobs.db"), ROOT, cfg, get_logger("test")))
    client = webapp.app.test_client()
    assert client.get("/").status_code == 200
    assert client.get("/new").status_code == 200
    docs = client.get("/docs")
    assert docs.status_code == 200 and b"{{CT_CONFIGURATION}}" in docs.data
    assert client.get("/experiments/missing").status_code == 404
    assert client.get("/experiments/..%2fetc").status_code == 404
    assert client.post("/api/preview", json={"yaml": "x: 1"}).status_code == 400  # no X-FBPP header
    r = client.post("/api/preview", json={"yaml": "experiment_name: ../x\ngroups: []"}, headers={"X-FBPP": "1"})
    assert r.get_json()["ok"] is False
    webapp.STATE["token"] = "s3cret"
    assert client.get("/").status_code == 403
    assert client.get("/?token=s3cret").status_code == 200
    assert client.get("/").status_code == 200        # the cookie is remembered
    webapp.STATE["token"] = None
