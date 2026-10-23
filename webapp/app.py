"""ConfigFuzzEval web app: configure, run and follow experiments, and read their results.

    python3 webapp/app.py [--config config.yaml] [--host 127.0.0.1] [--port 8800] [--token SECRET]

It starts the same command lines as the docs (common/run_experiment.py with an
experiment file, common/post_analysis.py) and reads what they write, so the command
line and the web app can be used side by side. Docker access is root-equivalent: keep
the app on localhost (reach it through an SSH tunnel) or give it a --token.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid

import yaml
from flask import Flask, abort, jsonify, make_response, render_template, request, send_from_directory

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "common"))
sys.path.insert(0, HERE)

import catalog as catalog_mod          # noqa: E402
import events                          # noqa: E402
import experiments as exps             # noqa: E402
import live_view                       # noqa: E402
import superc_view                     # noqa: E402
import triage_view                     # noqa: E402
from color_logger import get_logger    # noqa: E402
import experiment_plan                 # noqa: E402
from jobs import DB_PATH, Jobs, ensure_worker, external_processes, queue_experiment  # noqa: E402

logging = get_logger("webapp")
INSTANCE = os.path.join(HERE, "instance")
TEXT_SUFFIXES = (".log", ".txt", ".json", ".jsonl", ".yaml", ".yml", ".csv", ".html", ".svg", ".png")

app = Flask(__name__, template_folder=os.path.join(HERE, "templates"), static_folder=os.path.join(HERE, "static"))
STATE = {}


def config():
    return STATE["config"]


def jobs():
    return STATE["jobs"]


# ---------------------------------------------------------------------------
# Access: optional token, and a header on every change so other sites cannot post here
# ---------------------------------------------------------------------------

@app.before_request
def check_access():
    token = STATE.get("token")
    if token:
        given = request.args.get("token") or request.cookies.get("fbpp_token")
        if given != token:
            return make_response("Forbidden: open the app with ?token=<token>", 403)
    if request.method == "POST" and request.headers.get("X-FBPP") != "1":
        return make_response("Missing X-FBPP header", 400)


@app.after_request
def remember_token(resp):
    token = STATE.get("token")
    if token and request.args.get("token") == token:
        resp.set_cookie("fbpp_token", token, httponly=True, samesite="Strict")
    return resp


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def running_names():
    names = {j["name"] for j in jobs().all() if j["status"] in ("running", "cancelling")}
    names |= {p["name"] for p in external_processes(PROJECT_ROOT, exclude_pids=job_pids()) if p["name"]}
    return names


def job_pids():
    return {j["pid"] for j in jobs().all() if j["pid"] and j["status"] in ("running", "cancelling")}


def experiment_path(name):
    if not exps.valid_name(name):
        abort(404)
    return os.path.join(config()["experiment_filestore"], name)


def experiment_log(name):
    for job in jobs().for_experiment(name):
        if job["kind"] == "experiment" and os.path.isfile(job["log_path"]):
            return job["log_path"]
    path = experiment_plan.log_path(name)
    return path if os.path.isfile(path) else None


_system_cache = {}


def system_checks():
    """Host checks from docs/README.md: Docker, core_pattern and the CPU governor, cores, disk."""
    if _system_cache.get("time", 0) > time.time() - 30:
        return _system_cache["checks"]
    checks = []
    try:
        r = subprocess.run(["docker", "info", "--format", "{{.ServerVersion}}"], capture_output=True,
                           text=True, timeout=15)
        checks.append({"name": "Docker", "ok": r.returncode == 0,
                       "detail": f"server {r.stdout.strip()}" if r.returncode == 0 else r.stderr.strip()[:200]})
    except (OSError, subprocess.TimeoutExpired) as e:
        checks.append({"name": "Docker", "ok": False, "detail": str(e)})
    try:
        pattern = open("/proc/sys/kernel/core_pattern").read().strip()
        checks.append({"name": "core_pattern", "ok": pattern == "core",
                       "detail": f"'{pattern}'" + ("" if pattern == "core" else " (AFL++ needs 'core': run run_as_sudo.sh)")})
    except OSError:
        pass
    governors = set()
    for cpu in os.listdir("/sys/devices/system/cpu"):
        p = f"/sys/devices/system/cpu/{cpu}/cpufreq/scaling_governor"
        if re.match(r"cpu\d+$", cpu) and os.path.isfile(p):
            governors.add(open(p).read().strip())
    if governors:
        checks.append({"name": "CPU governor", "ok": governors == {"performance"},
                       "detail": ", ".join(sorted(governors)) +
                                 ("" if governors == {"performance"} else " (run run_as_sudo.sh for 'performance')")})
    cfg = config()
    ncpu = os.cpu_count() or 0
    first = cfg.get("first_core")
    checks.append({"name": "Cores", "ok": cfg["cores_to_use"] <= ncpu,
                   "detail": f"{cfg['cores_to_use']} of {ncpu} configured" +
                             (f", from core {first}" if first is not None else "")})
    try:
        os.makedirs(cfg["experiment_filestore"], exist_ok=True)
        free = shutil.disk_usage(cfg["experiment_filestore"]).free / 2 ** 30
        checks.append({"name": "Disk", "ok": free > 20,
                       "detail": f"{free:.0f} GiB free in {cfg['experiment_filestore']}"})
    except OSError as e:
        checks.append({"name": "Disk", "ok": False, "detail": str(e)})
    _system_cache.update(time=time.time(), checks=checks)
    return checks


def dry_run(experiment_yaml):
    """Validates an experiment file with run_experiment.py --dry-run; (ok, plan, output, data)."""
    try:
        data = yaml.safe_load(experiment_yaml)
    except yaml.YAMLError as e:
        return False, None, f"The experiment file is not valid YAML:\n{e}", None
    if not isinstance(data, dict):
        return False, None, "The experiment file must be a YAML mapping with experiment_name and groups.", None
    name = data.get("experiment_name")
    if not exps.valid_name(str(name or "")):
        return False, None, ("experiment_name is required and may only use letters, digits, '.', '_' and '-' "
                             "(it becomes a folder name)."), data
    os.makedirs(os.path.join(INSTANCE, "previews"), exist_ok=True)
    tmp = os.path.join(INSTANCE, "previews", f"{uuid.uuid4().hex}")
    with open(tmp + ".yaml", "w") as f:
        f.write(experiment_yaml)
    try:
        r = subprocess.run([sys.executable, "common/run_experiment.py", "--config", STATE["config_path"],
                            "--experiment", tmp + ".yaml", "--dry-run", "--plan-json", tmp + ".json"],
                           cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=300)
        output = exps.ANSI.sub("", r.stdout + r.stderr)
        plan = None
        if r.returncode == 0 and os.path.isfile(tmp + ".json"):
            with open(tmp + ".json") as f:
                plan = json.load(f)
        return r.returncode == 0 and plan is not None, plan, output, data
    except subprocess.TimeoutExpired:
        return False, None, "The dry run took longer than 5 minutes.", data
    finally:
        for suffix in (".yaml", ".json"):
            try:
                os.remove(tmp + suffix)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    running = running_names()
    rows = [exps.summary(config(), e["name"], running) for e in exps.list_experiments(config())]
    queued = [j for j in jobs().all() if j["status"] == "queued"]
    external = external_processes(PROJECT_ROOT, exclude_pids=job_pids())
    return render_template("index.html", experiments=rows, queued=queued, external=external,
                           checks=system_checks(), recent_jobs=jobs().all(limit=15))


@app.route("/new")
def new():
    cat = catalog_mod.load(PROJECT_ROOT)
    initial = ""
    source = request.args.get("from")
    if source and exps.valid_name(source):
        for ext in (".yaml", ".json"):
            p = os.path.join(experiment_path(source), "experiment" + ext)
            if os.path.isfile(p):
                with open(p) as f:
                    loaded = yaml.safe_load(f) or {}
                loaded.pop("record", None)
                loaded["experiment_name"] = f"{source}_rerun"
                initial = yaml.safe_dump(loaded, sort_keys=False)
                break
    defaults = {"trials": config()["trials"], "max_total_time": config()["max_total_time"]}
    return render_template("new.html", catalog=cat, defaults=defaults, initial_yaml=initial, source=source)


@app.route("/docs")
def docs():
    return render_template("docs.html", catalog=catalog_mod.load(PROJECT_ROOT))


@app.route("/experiments/<name>")
def experiment(name):
    path = experiment_path(name)
    if not os.path.isdir(path) and not jobs().for_experiment(name):
        abort(404)
    state = exps.load_state(path)
    exp_file = next((f for f in ("experiment.yaml", "experiment.json") if os.path.isfile(os.path.join(path, f))), None)
    exp_text = open(os.path.join(path, exp_file)).read() if exp_file else ""
    saved = experiment_plan.saved_experiment_path(name)
    if os.path.isfile(saved):        # with its record: start, estimated end, stop command
        exp_text = open(saved).read()
    others = [e["name"] for e in exps.list_experiments(config()) if e["name"] != name]
    stats_dir = os.path.join(config()["report_filestore"], name, "statistics")
    stats_files = sorted(os.listdir(stats_dir)) if os.path.isdir(stats_dir) else []
    superc_report = superc_view.has_report(config(), name)
    return render_template("experiment.html", name=name, state=state, experiment_text=exp_text,
                           others=others, stats_files=stats_files, superc_report=superc_report,
                           no_superc=bool((state or {}).get("no_superc")),
                           triagers=(state or {}).get("built_triagers") or [],
                           fuzzers=(state or {}).get("fuzzers") or [])


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

@app.post("/api/preview")
def api_preview():
    text = (request.get_json(silent=True) or {}).get("yaml", "")
    ok, plan, output, data = dry_run(text)
    name = (data or {}).get("experiment_name") if isinstance(data, dict) else None
    taken = bool(plan and plan.get("exists")) or (name in jobs().active_names())
    return jsonify(ok=ok and not taken, plan=plan, output=output,
                   error=None if ok and not taken else
                   (f"An experiment named {name} already exists or is queued; choose another name." if ok else
                    "The experiment cannot run as given; see the output below."))


@app.post("/api/experiments")
def api_create():
    text = (request.get_json(silent=True) or {}).get("yaml", "")
    ok, plan, output, data = dry_run(text)
    if not ok:
        return jsonify(ok=False, error="The experiment cannot run as given.", output=output), 400
    name = data["experiment_name"]
    if plan.get("exists") or name in jobs().active_names():
        return jsonify(ok=False, error=f"An experiment named {name} already exists or is queued."), 409
    # The same queue as run_experiment.py from a terminal: saved as experiments/<name>.yaml.
    try:
        job_id, _, _ = queue_experiment(STATE["config_path"], data, config())
    except ValueError as e:
        return jsonify(ok=False, error=str(e)), 409
    return jsonify(ok=True, job_id=job_id, name=name, url=f"/experiments/{name}")


@app.get("/api/experiments/<name>/status")
def api_status(name):
    path = experiment_path(name)
    running = name in running_names()
    summary = exps.summary(config(), name, {name} if running else ())
    exp_jobs = jobs().for_experiment(name)
    if not running and any(j["status"] == "queued" and j["kind"] == "experiment" for j in exp_jobs) \
            and not os.path.isdir(path):
        summary["status"] = "queued"
    return jsonify(summary=summary, trials=exps.trials(config(), name, running), jobs=exp_jobs,
                   phases=[e for e in events.read(path) if e["event"] in ("phase", "finished")],
                   stats=exps.statistics_path(config(), name) is not None, now=time.time())


@app.get("/api/experiments/<name>/live")
def api_live(name):
    """The Live tab: every trial, the running ones with the fuzzer's own statistics."""
    experiment_path(name)
    return jsonify(live_view.overview(config(), name, name in running_names()))


@app.get("/api/experiments/<name>/trial/<folder>")
def api_trial(name, folder):
    """One trial's fuzzer_stats, charts, crash files and logs, for the Live tab's detail window."""
    experiment_path(name)
    data = live_view.trial(config(), name, folder, name in running_names())
    if data is None:
        abort(404)
    return jsonify(data)


@app.get("/api/experiments/<name>/superc")
def api_superc(name):
    experiment_path(name)
    data = superc_view.overview(config(), name)
    return jsonify(ok=data is not None, **(data or {}))


@app.get("/api/experiments/<name>/triage")
def api_triage(name):
    """Every triager's results: bugs per arm and benchmark, each bug, each triaged benchmark copy."""
    return jsonify(triage_view.summary(experiment_path(name)))


@app.get("/api/experiments/<name>/superc/strategies")
def api_superc_strategies(name):
    experiment_path(name)
    data = superc_view.cross_overview(config(), name)
    return jsonify(ok=data is not None, benchmarks=data or {})


@app.get("/api/experiments/<name>/superc/strategies/<benchmark>/conditions")
def api_superc_strategy_conditions(name, benchmark):
    experiment_path(name)
    if not re.match(r"^[A-Za-z0-9_.+-]+$", benchmark) or ".." in benchmark:
        abort(404)
    data = superc_view.cross_conditions(config(), name, benchmark, request.args.get("arm", superc_view.ALL_ARMS),
                                        show=request.args.get("show", "all"), strategy=request.args.get("strategy") or None,
                                        query=request.args.get("q", ""), offset=request.args.get("offset", 0, type=int),
                                        limit=request.args.get("limit", 100, type=int))
    if data is None:
        abort(404)
    return jsonify(ok=True, **data)


@app.get("/api/experiments/<name>/superc/<key>/conditions")
def api_superc_conditions(name, key):
    experiment_path(name)
    if not re.match(r"^[A-Za-z0-9_.+-]+$", key) or ".." in key:
        abort(404)
    data = superc_view.conditions(config(), name, key, show=request.args.get("show", "all"),
                                  arm=request.args.get("arm") or None, query=request.args.get("q", ""),
                                  sort=request.args.get("sort", "instrumented"),
                                  offset=request.args.get("offset", 0, type=int),
                                  limit=request.args.get("limit", 100, type=int))
    if data is None:
        abort(404)
    return jsonify(ok=True, **data)


@app.get("/api/experiments/<name>/timeline")
def api_timeline(name):
    """Coverage after every round of a continuous campaign: {benchmark: {arm: [[hours, median, min, max, n]]}}."""
    path = experiment_path(name)
    metric = request.args.get("metric", "branches")
    if metric not in ("branches", "lines", "regions", "functions"):
        abort(400)
    from statistical_analysis import coverage_over_time
    series = coverage_over_time(path, metric, [])
    return jsonify(ok=bool(series), metric=metric, benchmarks=series)


@app.post("/api/experiments/<name>/continuous/<action>")
def api_continuous(name, action):
    """Asks a running continuous campaign for a coverage round now, or to stop after a last round."""
    path = experiment_path(name)
    if action not in ("round", "stop"):
        abort(404)
    state = exps.load_state(path)
    if not state or state.get("mode") != "continuous":
        return jsonify(ok=False, error="This experiment is not a continuous campaign."), 400
    if name not in running_names():
        return jsonify(ok=False, error="The campaign is not running."), 409
    import continuous
    continuous.request(path, action)
    return jsonify(ok=True)


@app.get("/api/experiments/<name>/log")
def api_log(name):
    experiment_path(name)
    job_id = request.args.get("job", type=int)
    path = None
    if job_id:
        job = jobs().get(job_id)
        path = job["log_path"] if job and job["name"] == name else None
    else:
        path = experiment_log(name)
    if not path or not os.path.isfile(path):
        return jsonify(text="", offset=0, size=0)
    offset = request.args.get("offset", default=-1, type=int)
    size = os.path.getsize(path)
    if offset < 0 or offset > size:
        text = exps.tail(path, 60_000)
        return jsonify(text=text, offset=size, size=size)
    with open(path, "rb") as f:
        f.seek(offset)
        chunk = f.read(min(size - offset, 1_000_000)).decode("utf-8", errors="replace")
    return jsonify(text=exps.ANSI.sub("", chunk), offset=offset + len(chunk.encode()), size=size)


@app.post("/api/experiments/<name>/post")
def api_post(name):
    path = experiment_path(name)
    state_path = os.path.join(path, "experiment_state.pkl")
    if not os.path.isfile(state_path):
        return jsonify(ok=False, error="This experiment has no experiment_state.pkl."), 400
    if name in running_names():
        return jsonify(ok=False, error="The experiment is still running."), 409
    body = request.get_json(silent=True) or {}
    args, parts = [], []
    if body.get("triage"):
        args.append("--triage"); parts.append("triage")
    if body.get("per_config"):
        args.append("--per-config-coverage"); parts.append("per-configuration coverage")
    if body.get("superc"):
        args.append("--superc"); parts.append("SuperC presence conditions")
    if body.get("stats"):
        args.append("--stats"); parts.append("statistics")
        metric = body.get("metric") or "branches"
        if metric not in ("branches", "lines", "regions", "functions"):
            return jsonify(ok=False, error="Unknown metric."), 400
        args += ["--metric", metric]
        if body.get("baseline"):
            if not re.match(r"^[A-Za-z0-9_.-]+$", body["baseline"]):
                return jsonify(ok=False, error="Bad baseline."), 400
            args += ["--baseline", body["baseline"]]
        if body.get("compare_to"):
            other = experiment_path(body["compare_to"])
            if not os.path.isdir(other):
                return jsonify(ok=False, error="Unknown experiment to compare with."), 400
            args += ["--compare-to", other]
    if not args:
        return jsonify(ok=False, error="Choose at least one analysis."), 400
    command = [sys.executable, "common/post_analysis.py", "--state", state_path, *args]
    log_path = os.path.join(experiment_plan.LOGS_DIR, f"{name}_post_{int(time.time())}.log")
    job_id = jobs().enqueue("post", name, f"{', '.join(parts).capitalize()} for {name}", command, log_path)
    ensure_worker(STATE["config_path"])
    return jsonify(ok=True, job_id=job_id)


@app.post("/api/jobs/<int:job_id>/cancel")
def api_cancel(job_id):
    return jsonify(ok=jobs().cancel(job_id))


@app.get("/api/jobs")
def api_jobs():
    return jsonify(jobs=jobs().all(limit=50),
                   external=external_processes(PROJECT_ROOT, exclude_pids=job_pids()))


# ---------------------------------------------------------------------------
# Files: experiment data (text only) and reports
# ---------------------------------------------------------------------------

@app.get("/experiments/<name>/files/<path:rel>")
def experiment_file(name, rel):
    path = experiment_path(name)
    if not rel.endswith(TEXT_SUFFIXES):
        abort(404)
    full = os.path.realpath(os.path.join(path, rel))
    if not full.startswith(os.path.realpath(path) + os.sep) or not os.path.isfile(full):
        abort(404)
    if rel.endswith(".log"):
        resp = make_response(exps.tail(full, 2_000_000))
        resp.mimetype = "text/plain"
        return resp
    return send_from_directory(path, rel, mimetype="text/plain" if rel.endswith(".jsonl") else None)


@app.get("/reports/<name>/<path:rel>")
def report_file(name, rel):
    if not exps.valid_name(name):
        abort(404)
    return send_from_directory(os.path.join(config()["report_filestore"], name), rel)


@app.template_filter("ago")
def ago(ts):
    if not ts:
        return "–"
    d = time.time() - ts
    for unit, s in (("d", 86400), ("h", 3600), ("min", 60)):
        if d >= s:
            return f"{int(d // s)} {unit} ago"
    return "just now"


@app.template_filter("when")
def when(ts):
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts)) if ts else "–"


def main():
    parser = argparse.ArgumentParser(description="ConfigFuzzEval web app")
    parser.add_argument("--config", default="config.yaml", help="Configuration file (relative to the project root)")
    parser.add_argument("--host", default="127.0.0.1", help="Address to listen on (default: localhost only)")
    parser.add_argument("--port", type=int, default=8800)
    parser.add_argument("--token", default=os.environ.get("FBPP_WEBAPP_TOKEN"),
                        help="Require ?token=<token> once per browser (also FBPP_WEBAPP_TOKEN)")
    args = parser.parse_args()
    if args.host not in ("127.0.0.1", "localhost", "::1") and not args.token:
        parser.error("Listening beyond localhost needs --token: whoever reaches the app can run Docker as root.")
    config_path = args.config if os.path.isabs(args.config) else os.path.join(PROJECT_ROOT, args.config)
    with open(config_path) as f:
        STATE["config"] = yaml.safe_load(f)
    STATE["config_path"] = config_path
    STATE["token"] = args.token
    STATE["jobs"] = Jobs(DB_PATH, PROJECT_ROOT, STATE["config"], logging)
    STATE["jobs"].start_worker()        # ticks the shared queue while the app runs
    ensure_worker(STATE["config_path"])  # and the background worker, for jobs queued while it was down
    logging.info(f"ConfigFuzzEval web app on http://{args.host}:{args.port}/" + ("?token=..." if args.token else ""))
    app.run(host=args.host, port=args.port, threaded=True, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
