"""Continuous mode's campaign (common/continuous.py), with Docker and the clock replaced."""
import json
import os
import sys
from types import SimpleNamespace

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "common"))

import continuous
import events
import experiment_plan


class FakeDocker:
    """Records docker commands; containers run until `exits` says otherwise."""
    def __init__(self):
        self.calls, self.exits = [], {}

    def __call__(self, args, log_file=None, check=False):
        self.calls.append(args)
        if args[0] == "inspect":
            code = self.exits.get(args[-1])
            return SimpleNamespace(returncode=0, stdout="true 0" if code is None else f"false {code}")
        return SimpleNamespace(returncode=0, stdout="")

    def runs(self, role):
        return [a for a in self.calls if a[0] == "run" and f"fbpp.role={role}" in a]


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def make_state(tmp_path, duration=300, interval=60, coverage_cores=2):
    exp = tmp_path / "exp" / "camp"
    (exp / "data").mkdir(parents=True)
    rt = tmp_path / "rt.json"
    rt.write_text(json.dumps({"configs": [["-a"], ["-b"], ["-c"]]}))
    tasks = [("aflplusplus", "default", "cts_default_xz_xz_0", 0, 1, None, 3600),
             ("aflplusplus", "default", "cts_default_xz_xz_0", 1, 1, None, 3600),
             ("aflplusplus", "random", "cts_default_xz_xz_0", 0, 1, str(rt), 3600)]
    return {"experiment_path": str(exp), "project_root": ROOT, "cores_range": (10, 15), "trial_tasks": tasks,
            "continuous": {"interval": interval, "coverage_cores": coverage_cores, "duration": duration},
            "rt_supported_fuzzers": {"aflplusplus": {"corpus_dir": "default/queue"}},
            "memory_per_experiment_gb": 2, "no_superc": True, "built_triagers": [],
            "report_filestore": str(tmp_path / "rep")}


def make_campaign(tmp_path, **kw):
    clock, docker = Clock(), FakeDocker()
    c = continuous.Campaign(make_state(tmp_path, **kw), docker=docker, clock=clock, sleep=clock.sleep)
    c.coverage_runs = []
    c._coverage = lambda inst, cpu, min_age: c.coverage_runs.append((c.round, inst["index"], cpu, min_age)) or True
    c._snapshot = lambda final: {"new_inputs": 0}
    c._analyses = lambda: None
    return c, docker, clock


def test_cpus_split_and_instances(tmp_path):
    c, _, _ = make_campaign(tmp_path)
    assert c.fuzz_cpus == [10, 11, 12, 13] and c.coverage_cpus == [14, 15]
    assert [i["cpu"] for i in c.instances] == [10, 11, 12]
    assert [i["label"] for i in c.instances] == ["aflplusplus", "aflplusplus", "aflplusplus_rts_random"]


def test_rounds_rotation_and_final_round(tmp_path):
    c, docker, clock = make_campaign(tmp_path, duration=300, interval=60)
    c.run()
    # rounds at 60, 120, 180, 240; the campaign ends at 300 with a last round
    assert c.round == 5
    rounds = sorted({r for r, *_ in c.coverage_runs})
    assert rounds == [1, 2, 3, 4, 5]
    assert all(cpu in (14, 15) for *_, cpu, _ in c.coverage_runs)          # coverage only on coverage CPUs
    assert {m for r, _, _, m in c.coverage_runs if r == 5} == {0}           # the last round takes every input
    assert {m for r, _, _, m in c.coverage_runs if r < 5} == {continuous.MIN_INPUT_AGE}
    fuzz = docker.runs("fuzz")
    assert all("RUNTIME=0" in a for a in fuzz)
    assert {a[a.index("--name") + 1] for a in fuzz} == {"fbpp-camp-0", "fbpp-camp-1", "fbpp-camp-2"}
    cpusets = {a[a.index("--name") + 1]: next(x for x in a if x.startswith("--cpuset-cpus=")) for a in fuzz}
    assert cpusets == {"fbpp-camp-0": "--cpuset-cpus=10", "fbpp-camp-1": "--cpuset-cpus=11", "fbpp-camp-2": "--cpuset-cpus=12"}
    assert any(a[-1].endswith("run.sh:ro") or "run.sh:ro" in " ".join(a) for a in fuzz)
    # the runtime-strategy instance: started once, then moved on at each of the 4 regular rounds
    rts = [a for a in fuzz if "fbpp-camp-2" in a]
    assert len(rts) == 5 and [a[a.index("-e") + 1] for a in rts][0] == "RUNTIME=0"
    assert [next(x for x in a if x.startswith("CONFIG_INDEX=")) for a in rts] == [f"CONFIG_INDEX={n}" for n in range(5)]
    trial = tmp_path / "exp" / "camp" / "data" / "aflplusplus_rts_random_cts_default_xz_xz_0_trial_0"
    used = json.loads((trial / "rt_configs.json").read_text())["configs"]
    assert used == [["-a"], ["-b"], ["-c"], ["-a"], ["-b"]]                 # configs[n % 3]
    log = [json.loads(l) for l in (trial / "rt_run.jsonl").read_text().splitlines()]
    assert [e["config"] for e in log] == [0, 1, 2, 3, 4] and os.readlink(trial / "default") == "config_4/default"
    # every container is removed at the end, and every trial ends as a success
    evs = events.read(c.path)
    ends = [e for e in evs if e["event"] == "trial_end"]
    assert len(ends) == 3 and {e["status"] for e in ends} == {"success"}
    assert [e["round"] for e in evs if e["event"] == "round_end"] == [1, 2, 3, 4, 5]
    status = continuous.read_status(c.path)
    assert status["round"] == 5 and status["stopping"] and not any(i["running"] for i in status["instances"])


def test_exited_instance_is_reported_and_not_restarted(tmp_path):
    c, docker, clock = make_campaign(tmp_path, duration=200, interval=60)
    docker.exits["fbpp-camp-1"] = 1
    c.run()
    ends = {(e["run"], e["trial"]): e for e in events.read(c.path) if e["event"] == "trial_end"}
    assert ends[("aflplusplus", 1)]["status"] == "failure" and "code 1" in ends[("aflplusplus", 1)]["reason"]
    assert ends[("aflplusplus", 0)]["status"] == "success"
    assert len([a for a in docker.runs("fuzz") if "fbpp-camp-1" in a]) == 1   # started once only
    assert any(e["event"] == "instance_exit" for e in events.read(c.path))


def test_round_and_stop_requests(tmp_path):
    c, docker, clock = make_campaign(tmp_path, duration=None, interval=3600)
    sleeps = []

    def sleep(seconds):
        clock.now += seconds
        sleeps.append(seconds)
        if len(sleeps) == 2:
            continuous.request(c.path, "round")     # a round now, long before the hour
        if len(sleeps) == 6:
            continuous.request(c.path, "stop")
    c.sleep = sleep
    c.run()
    assert c.round == 2                               # the requested round, then the last one
    assert not os.path.exists(os.path.join(c.path, "continuous", "control", "round"))


def test_plan_needs_a_cpu_per_instance(tmp_path):
    state = make_state(tmp_path, coverage_cores=4)    # 6 CPUs - 4 = 2 fuzzing CPUs for 3 instances
    try:
        continuous.Campaign(state, docker=FakeDocker())
    except RuntimeError as e:
        assert "3 instance(s)" in str(e)
    else:
        raise AssertionError("expected an error")


def test_experiment_file_settings(tmp_path):
    p = tmp_path / "e.yaml"
    p.write_text("experiment_name: a\nmode: continuous\ncontinuous: {interval: 600}\n"
                 "groups: [{fuzzers: [aflplusplus], benchmarks: [xz_xz]}]\n")
    data = experiment_plan.load_experiment_file(str(p))
    assert data["continuous"] == {"interval": 600, "coverage_cores": 1, "duration": None}
    runs = [{"compiletime": "default", "benchmark": "xz_xz", "trials": 3}]
    assert experiment_plan.continuous_instances(runs, {("default", "xz_xz"): 2}) == 6
    assert experiment_plan.estimate_continuous_seconds(runs, {("default", "xz_xz"): 2}, {"cores_to_use": 4}, None) is None


def test_web_routes(tmp_path, monkeypatch):
    """The web app's campaign status, coverage-over-time and round/stop routes."""
    import pickle
    sys.path.insert(0, os.path.join(ROOT, "webapp"))
    import app as webapp
    import jobs as jobs_mod
    from color_logger import get_logger
    exp = tmp_path / "exp" / "camp"
    (exp / "continuous").mkdir(parents=True)
    pickle.dump({"mode": "continuous", "trial_tasks": [], "continuous": {"interval": 60}}, open(exp / "experiment_state.pkl", "wb"))
    with open(exp / "continuous" / "timeline.jsonl", "w") as f:
        for r, v in ((1, [10, 20]), (2, [30, 50])):
            f.write(json.dumps({"round": r, "elapsed": r * 3600, "trials": [
                {"arm": "afl", "benchmark": "xz_xz", "trial": i, "values": {"branches": x}} for i, x in enumerate(v)]}) + "\n")
    (exp / "continuous" / "status.json").write_text(json.dumps(
        {"round": 2, "next_round": 1.0, "instances": [{"label": "afl", "running": True}, {"label": "afl", "running": False, "exit_code": 1}]}))
    cfg = {"experiment_filestore": str(tmp_path / "exp"), "report_filestore": str(tmp_path / "rep"),
           "trials": 1, "max_total_time": 60, "cores_to_use": 1}
    monkeypatch.setattr(webapp, "external_processes", lambda *a, **k: [])
    monkeypatch.setattr(webapp, "system_checks", lambda: [])
    webapp.STATE.update(config=cfg, config_path="config.yaml", token=None,
                        jobs=jobs_mod.Jobs(str(tmp_path / "jobs.db"), ROOT, cfg, get_logger("test")))
    client = webapp.app.test_client()
    r = client.get("/api/experiments/camp/timeline?metric=branches").get_json()
    assert r["ok"] and r["benchmarks"]["xz_xz"]["afl"] == [[1.0, 15.0, 10, 20, 2], [2.0, 40.0, 30, 50, 2]]
    assert client.get("/api/experiments/camp/timeline?metric=bogus").status_code == 400
    s = client.get("/api/experiments/camp/status").get_json()["summary"]
    assert s["mode"] == "continuous" and s["continuous"]["round"] == 2 and s["continuous"]["fuzzing"] == 1
    assert len(s["continuous"]["exited"]) == 1
    h = {"X-FBPP": "1"}
    assert client.post("/api/experiments/camp/continuous/stop", json={}, headers=h).status_code == 409   # not running
    monkeypatch.setattr(webapp, "running_names", lambda: {"camp"})
    assert client.post("/api/experiments/camp/continuous/round", json={}, headers=h).get_json()["ok"]
    assert (exp / "continuous" / "control" / "round").exists()
    assert client.post("/api/experiments/camp/continuous/nope", json={}, headers=h).status_code == 404
    page = client.get("/experiments/camp")
    assert page.status_code == 200 and b'id="campaign"' in page.data
