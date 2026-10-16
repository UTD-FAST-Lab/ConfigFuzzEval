"""The web app's job queue: experiments and post-analyses, run one at a time.

A job is a command line (common/run_experiment.py or common/post_analysis.py) started
as its own detached process group, so it keeps running when the web app stops; the
queue only lives in a small SQLite file (webapp/instance/jobs.db). Jobs never run next
to another experiment, including one started from the command line, since they would
share the cores and the benchmark copies (see README.md).
"""
import json
import os
import signal
import sqlite3
import subprocess
import threading
import time

import events

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

    def cancel(self, job_id):
        job = self.get(job_id)
        if not job or job["status"] not in ACTIVE:
            return False
        if job["status"] == "queued":
            self._set(job_id, status="cancelled", ended=time.time())
            return True
        self._set(job_id, status="cancelling")
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
        with self.lock:
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
