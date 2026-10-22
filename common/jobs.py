"""The job queue of ConfigFuzzEval: experiments and post-analyses, run one at a time.

Every experiment goes through it, however it is started: run_experiment.py (with flags,
an experiment file or no flags) and the web app queue it here. A job is a command line
(common/run_experiment.py --foreground, or common/post_analysis.py) started as its own
detached session (like setsid nohup), so it keeps running when the terminal or the web
app is closed, with its output in experiments/logs/<name>.log. The queue lives in a small
SQLite file (webapp/instance/jobs.db); a background worker (python3 common/jobs.py worker,
started when a job is queued) starts the next job when the machine is free, and the
web app ticks the same queue while it runs. Jobs never run next to another experiment,
including one run with --foreground by hand, since they would share the cores and the
benchmark copies (see README.md).

    python3 common/jobs.py list            # the queue
    python3 common/jobs.py stop NAME       # cancel a queued experiment, or stop a running one
"""
import argparse
import fcntl
import json
import os
import signal
import sqlite3
import subprocess
import sys
import threading
import time

import events
import experiment_plan

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSTANCE = os.path.join(PROJECT_ROOT, "webapp", "instance")
DB_PATH = os.path.join(INSTANCE, "jobs.db")

ACTIVE = ("queued", "running", "cancelling")


class Jobs:
    def __init__(self, db_path, project_root, config, logging):
        self.db_path = db_path
        self.project_root = project_root
        self.config = config
        self.log = logging
        self.procs = {}           # job id -> Popen, for jobs started by this process
        self.lock = threading.Lock()
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        with self._db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, name TEXT, title TEXT, command TEXT,
                status TEXT, pid INTEGER, returncode INTEGER, log_path TEXT,
                created REAL, started REAL, ended REAL)""")

    def _db(self):
        db = sqlite3.connect(self.db_path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    # ---- queries ----

    def all(self, limit=200):
        with self._db() as db:
            return [dict(r) for r in db.execute("SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,))]

    def get(self, job_id):
        with self._db() as db:
            r = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            return dict(r) if r else None

    def for_experiment(self, name):
        with self._db() as db:
            return [dict(r) for r in db.execute("SELECT * FROM jobs WHERE name = ? ORDER BY id DESC", (name,))]

    def active_names(self):
        with self._db() as db:
            return {r["name"] for r in db.execute(
                f"SELECT name FROM jobs WHERE status IN ({','.join('?' * len(ACTIVE))})", ACTIVE)}

    def _set(self, job_id, **fields):
        with self._db() as db:
            db.execute(f"UPDATE jobs SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?",
                       (*fields.values(), job_id))

    # ---- changes ----

    def enqueue(self, kind, name, title, command, log_path):
        with self._db() as db:
            cur = db.execute("INSERT INTO jobs (kind, name, title, command, status, log_path, created) "
                             "VALUES (?, ?, ?, ?, 'queued', ?, ?)",
                             (kind, name, title, json.dumps(command), log_path, time.time()))
            return cur.lastrowid

    def cancel(self, job_id, wait=False):
        """Cancels a queued job, or stops a running one (in the background unless wait)."""
        job = self.get(job_id)
        if not job or job["status"] not in ACTIVE:
            return False
        if job["status"] == "queued":
            self._set(job_id, status="cancelled", ended=time.time())
            return True
        self._set(job_id, status="cancelling")
        if wait:
            self._kill(job)
        else:
            threading.Thread(target=self._kill, args=(job,), daemon=True).start()
        return True

    def _kill(self, job):
        pid = job["pid"]
        try:
            os.killpg(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, TypeError):
            pass
        for _ in range(30):
            if not pid_alive(pid):
                break
            time.sleep(0.5)
        else:
            try:
                os.killpg(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
        proc = self.procs.pop(job["id"], None)
        if proc is not None:
            proc.poll()          # reap it, so no zombie is left behind
        # The trial containers are not children of the process: stop them by their label.
        stop_containers(job["name"])
        if job["kind"] == "experiment":
            events.emit(os.path.join(self.config["experiment_filestore"], job["name"]), "phase", phase="cancelled")
        self._set(job["id"], status="cancelled", ended=time.time())
        self.log.info(f"Cancelled job {job['id']} ({job['title']})")

    # ---- the queue ----

    def start_worker(self, interval=2.0):
        def loop():
            while True:
                try:
                    self.tick()
                except Exception as e:      # keep the queue alive whatever happens
                    self.log.error(f"Job queue: {e}")
                time.sleep(interval)
        threading.Thread(target=loop, daemon=True, name="job-queue").start()

    def tick(self):
        # The web app and the background worker tick the same queue: one at a time.
        with self.lock, open(os.path.join(os.path.dirname(self.db_path), "queue.lock"), "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            for job in self.all():
                if job["status"] in ("running", "cancelling"):
                    self._refresh(job)
            busy = any(j["status"] in ("running", "cancelling") for j in self.all()) or external_processes(
                self.project_root, exclude_pids={j["pid"] for j in self.all() if j["pid"]})
            if busy:
                return
            with self._db() as db:
                nxt = db.execute("SELECT * FROM jobs WHERE status = 'queued' ORDER BY id LIMIT 1").fetchone()
            if nxt:
                self._start(dict(nxt))

    def _refresh(self, job):
        proc = self.procs.get(job["id"])
        if proc is not None:
            code = proc.poll()
            if code is None:
                return
            self.procs.pop(job["id"], None)
        elif pid_alive(job["pid"]):
            return
        else:
            code = None          # started before the web app restarted: the exit code is lost
        if job["status"] == "cancelling":
            return               # _kill marks it
        if code is None and job["kind"] == "experiment":
            finished = any(e["event"] == "finished" for e in
                           events.read(os.path.join(self.config["experiment_filestore"], job["name"])))
            status = "finished" if finished else "failed"
        else:
            status = "finished" if code == 0 else "failed"
        self._set(job["id"], status=status, returncode=code, ended=time.time())
        self.log.info(f"Job {job['id']} ({job['title']}) {status} (exit code {code})")

    def _start(self, job):
        command = json.loads(job["command"])
        os.makedirs(os.path.dirname(job["log_path"]), exist_ok=True)
        log = open(job["log_path"], "ab")
        proc = subprocess.Popen(command, cwd=self.project_root, stdout=log, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, start_new_session=True)
        log.close()
        self.procs[job["id"]] = proc
        self._set(job["id"], status="running", pid=proc.pid, started=time.time())
        self.log.info(f"Started job {job['id']} ({job['title']}), pid {proc.pid}")


def pid_alive(pid):
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:
        with open(f"/proc/{pid}/stat") as f:
            return f.read().split(")")[-1].split()[0] != "Z"
    except OSError:
        return False


def stop_containers(name):
    try:
        ids = subprocess.run(["docker", "ps", "-q", "--filter", f"label=fbpp.experiment={name}"],
                             capture_output=True, text=True, timeout=30).stdout.split()
        if ids:
            subprocess.run(["docker", "kill", *ids], capture_output=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        pass


def external_processes(project_root, exclude_pids=()):
    """Experiments and post-analyses running on this machine that the queue did not start
    (for example from a terminal), as [{"pid", "name", "script"}]."""
    out = []
    for entry in os.listdir("/proc"):
        if not entry.isdigit() or int(entry) in exclude_pids:
            continue
        try:
            with open(f"/proc/{entry}/cmdline", "rb") as f:
                argv = [a.decode(errors="replace") for a in f.read().split(b"\0") if a]
            cwd = os.readlink(f"/proc/{entry}/cwd")
        except OSError:
            continue
        script = next((a for a in argv if a.endswith(("run_experiment.py", "post_analysis.py"))), None)
        if not script or "--dry-run" in argv or not argv[0].split("/")[-1].startswith("python"):
            continue
        # run_experiment.py only runs an experiment with --foreground; without it, it
        # queues one (or asks what to run) and returns.
        if script.endswith("run_experiment.py") and "--foreground" not in argv:
            continue
        out.append({"pid": int(entry), "script": os.path.basename(script),
                    "name": process_experiment_name(argv, cwd)})
    return out


def process_experiment_name(argv, cwd):
    def arg(flag):
        if flag in argv and argv.index(flag) + 1 < len(argv):
            return argv[argv.index(flag) + 1]
        return None
    if arg("--experiment-name"):
        return arg("--experiment-name")
    state = arg("--state")
    if state:
        return os.path.basename(os.path.dirname(os.path.join(cwd, state)))
    exp = arg("--experiment") or arg("--groups")
    if exp:
        try:
            import yaml
            with open(os.path.join(cwd, exp)) as f:
                return (yaml.safe_load(f) or {}).get("experiment_name")
        except Exception:
            return None
    return None


# --- Queueing experiments -------------------------------------------------------

def queue(config, logging=None):
    return Jobs(DB_PATH, PROJECT_ROOT, config, logging or _logger())


def _logger():
    from color_logger import get_logger
    return get_logger("jobs")


def ensure_worker(config_path=None):
    """Starts the background worker unless one runs; it exits when the queue is empty."""
    os.makedirs(INSTANCE, exist_ok=True)
    with open(os.path.join(INSTANCE, "worker.lock"), "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False         # a worker holds the lock
    os.makedirs(experiment_plan.LOGS_DIR, exist_ok=True)
    with open(os.path.join(experiment_plan.LOGS_DIR, "queue_worker.log"), "ab") as log:
        config_args = ["--config", os.path.abspath(config_path)] if config_path else []
        subprocess.Popen([sys.executable, os.path.abspath(__file__), *config_args, "worker"], cwd=PROJECT_ROOT,
                         stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    return True


def queue_experiment(config_path, experiment, config):
    """Queues an experiment (a checked experiment file, as a dict) and starts the worker.

    Saves it as experiments/<name>.yaml with its record (queued time, stop command); the
    job runs run_experiment.py --foreground on that file, which adds the start and
    estimated end time when it starts. Returns (job id, saved file, log file).
    Raises ValueError if the name is already used, queued or running.
    """
    name = experiment["experiment_name"]
    jobs = queue(config)
    taken = [s for s in (config["experiment_filestore"], config["report_filestore"])
             if os.path.exists(os.path.join(s, name))]
    if taken:
        raise ValueError(f"Experiment {name} already exists in {' and '.join(taken)}; choose another name.")
    if name in jobs.active_names() or any(p["name"] == name for p in external_processes(PROJECT_ROOT)):
        raise ValueError(f"Experiment {name} is already queued or running; choose another name.")
    saved = experiment_plan.saved_experiment_path(name)
    experiment_plan.write_experiment_file(saved, experiment, {"queued": time.time()})
    log_path = experiment_plan.log_path(name)
    command = [sys.executable, os.path.join(PROJECT_ROOT, "common", "run_experiment.py"),
               "--config", os.path.abspath(config_path), "--experiment", saved, "--foreground"]
    job_id = jobs.enqueue("experiment", name, f"Experiment {name}", command, log_path)
    ensure_worker(config_path)
    return job_id, saved, log_path


def queue_message(jobs, job_id):
    """When a just-queued job starts: now, or after the running and queued jobs ahead of it."""
    active = [j for j in jobs.all() if j["status"] in ACTIVE]
    ahead = [j for j in active if j["status"] == "queued" and j["id"] < job_id]
    running = any(j["status"] != "queued" and j["id"] != job_id for j in active) or bool(external_processes(
        jobs.project_root, exclude_pids={j["pid"] for j in jobs.all() if j["pid"]}))
    if not ahead and not running:
        return "it starts now."
    waits = (["the running experiment"] if running else []) + \
            ([f"{len(ahead)} queued job(s) ahead of it"] if ahead else [])
    return f"it starts after {' and '.join(waits)}."


def stop(name, config):
    """Cancels or stops experiment |name|, from the queue or (run by hand) by its process.
    Returns "cancelled" (it was only queued), "stopped" (it was running) or None."""
    jobs = queue(config)
    found = None
    for job in jobs.for_experiment(name):
        if job["status"] in ACTIVE and jobs.cancel(job["id"], wait=True):
            found = found or ("cancelled" if job["status"] == "queued" else "stopped")
    for proc in external_processes(PROJECT_ROOT, exclude_pids={j["pid"] for j in jobs.all() if j["pid"]}):
        if proc["name"] == name:
            try:
                os.killpg(os.getpgid(proc["pid"]), signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
            stop_containers(name)
            events.emit(os.path.join(config["experiment_filestore"], name), "phase", phase="cancelled")
            found = "stopped"
    return found


def worker(config):
    """Ticks the queue until nothing is queued or running, then exits."""
    with open(os.path.join(INSTANCE, "worker.lock"), "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return               # another worker runs
        jobs = queue(config)
        idle = 0
        while idle < 5:
            try:
                jobs.tick()
            except Exception as e:      # keep the queue alive whatever happens
                jobs.log.error(f"Job queue: {e}")
            idle = 0 if any(j["status"] in ACTIVE for j in jobs.all()) else idle + 1
            time.sleep(2)


def main():
    import yaml
    parser = argparse.ArgumentParser(description="The ConfigFuzzEval job queue.")
    parser.add_argument("--config", default=os.path.join(PROJECT_ROOT, "config.yaml"),
                        help="Configuration file (for the result folders; default config.yaml)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="Show the queue and recent jobs")
    stop_parser = sub.add_parser("stop", help="Cancel a queued experiment, or stop a running one")
    stop_parser.add_argument("name")
    sub.add_parser("worker", help="Run the queue until it is empty (started automatically)")
    args = parser.parse_args()
    with open(args.config) as f:
        config = yaml.safe_load(f)
    if args.command == "worker":
        worker(config)
    elif args.command == "list":
        for job in reversed(queue(config).all(limit=30)):
            print(f"{job['id']:>4}  {job['status']:<10}  {job['title']:<40}  {job['log_path'] or ''}")
    elif args.command == "stop":
        result = stop(args.name, config)
        if result == "cancelled":
            print(f"Removed {args.name} from the queue; it had not started.")
        elif result == "stopped":
            print(f"Stopped {args.name}. Finished trials are kept; its containers were killed.")
        else:
            print(f"{args.name} is not queued or running.")
            sys.exit(1)


if __name__ == "__main__":
    main()
