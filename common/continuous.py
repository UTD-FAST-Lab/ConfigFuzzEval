"""Continuous mode: fuzz without a time limit, and measure coverage in rounds.

An experiment file with `mode: continuous` (see experiment_plan.py) runs as a campaign:

  * every trial of every benchmark copy is an instance: one fuzzing container on its own
    CPU, started without a time limit (RUNTIME=0; every fuzzers/*/run.sh then leaves out
    -V). The repository's run.sh is mounted over the one in the fuzzer image, so images
    built before run.sh supported this keep working;
  * `coverage_cores` CPUs are kept for coverage and the analyses. Every `interval` seconds
    a round replays, for every instance, the inputs found since the last round on the
    coverage build (runtime/continuous_coverage.py), adds them to the instance's cumulative
    profile and rewrites its coverage/report.{json,txt}; then the statistics report,
    SuperC and crash triage are redone (each as configured), so the web app stays current;
  * a runtime-strategy instance fuzzes one configuration per round: at every round it
    moves to the next of its configurations (runtime/continuous_run.sh), starting from the
    previous configuration's corpus, into config_<n>/ (n counts the rotations; rt_run.jsonl
    and the trial's rt_configs.json list them, as in evaluation mode);
  * the campaign ends after `duration` seconds, or when it is asked to stop (web app, or
    `python3 common/continuous.py stop EXPERIMENT`): the fuzzers are stopped and a last
    round takes every remaining input. Cancelling the job kills it without that round.

Per instance: data/<trial>/continuous/{processed.txt, rounds.jsonl}, the trial's usual
coverage/; per campaign: <experiment>/continuous/{status.json, timeline.jsonl, control/}.
timeline.jsonl has, per round, every trial's coverage as the statistics count it (the
union of a trial's benchmark copies), which the web app and the statistics report plot.
"""
import json
import os
import signal
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import events
from color_logger import get_logger
from docker_image_builder import experiment_label, run_label

POLL_SECONDS = 5           # how often the campaign checks the clock and its control files
CHECK_SECONDS = 30         # how often it checks that the fuzzing containers still run
MIN_INPUT_AGE = 30         # seconds an input must exist before a round takes it (see continuous_coverage.py)


def campaign_dir(experiment_path):
    return os.path.join(experiment_path, "continuous")


def request(experiment_path, what):
    """Asks a running campaign for a round now ("round") or to stop after a last round ("stop")."""
    if what not in ("round", "stop"):
        raise ValueError(what)
    control = os.path.join(campaign_dir(experiment_path), "control")
    os.makedirs(control, exist_ok=True)
    with open(os.path.join(control, what), "w") as f:
        f.write(str(time.time()))


def read_status(experiment_path):
    try:
        with open(os.path.join(campaign_dir(experiment_path), "status.json")) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def read_timeline(experiment_path):
    path = os.path.join(campaign_dir(experiment_path), "timeline.jsonl")
    out = []
    if os.path.isfile(path):
        with open(path) as f:
            for line in f:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
    return out


def split_cpus(state):
    """(fuzzing CPUs, coverage CPUs): one CPU per instance from the start of the experiment's
    cores, and the last coverage_cores ones for coverage and the analyses."""
    core_start, core_end = state["cores_range"]
    cpus = list(range(core_start, core_end + 1))
    n = state["continuous"]["coverage_cores"]
    return cpus[:-n], cpus[-n:]


class Campaign:
    def __init__(self, state, logging=None, docker=None, clock=time.time, sleep=time.sleep):
        self.state = state
        self.log = logging or get_logger(__name__)
        self.docker = docker or self._docker
        self.clock, self.sleep = clock, sleep
        self.path = state["experiment_path"]
        self.name = os.path.basename(os.path.normpath(self.path))
        self.settings = state["continuous"]
        self.project_root = state["project_root"]
        self.fuzz_cpus, self.coverage_cpus = split_cpus(state)
        self.memory = state.get("memory_per_experiment_gb") or 2
        self.instances = self._plan()
        self.round = 0
        self.started = None
        self.next_round = None
        self.stopping = False
        self.lock = threading.Lock()
        os.makedirs(os.path.join(campaign_dir(self.path), "control"), exist_ok=True)

    # --- Docker ------------------------------------------------------------------------

    @staticmethod
    def _docker(args, log_file=None, check=False):
        if log_file:
            with open(log_file, "a") as lf:
                return subprocess.run(["docker", *args], stdout=lf, stderr=subprocess.STDOUT, check=check)
        return subprocess.run(["docker", *args], capture_output=True, text=True, check=check)

    # --- Instances ---------------------------------------------------------------------

    def _plan(self):
        from run_experiment import trial_tasks
        tasks = trial_tasks(self.state)
        if len(tasks) > len(self.fuzz_cpus):
            raise RuntimeError(f"{len(tasks)} instance(s) but {len(self.fuzz_cpus)} fuzzing CPU(s)")
        rt_supported = self.state.get("rt_supported_fuzzers", {})
        out = []
        for i, (fuzzer, rts, benchmark, trial, _, rt_config_file, _) in enumerate(tasks):
            label = run_label(fuzzer, rts)
            configs = None
            if rts != "default":
                with open(rt_config_file) as f:
                    configs = json.load(f)["configs"]
                if not configs:
                    raise RuntimeError(f"Runtime strategy {rts} made no configurations for {benchmark}")
            out.append({"index": i, "fuzzer": fuzzer, "rts": rts, "benchmark": benchmark, "trial": trial,
                        "label": label, "cpu": self.fuzz_cpus[i], "configs": configs, "rotation": -1,
                        "corpus_dir": rt_supported.get(fuzzer, {}).get("corpus_dir", "default/queue")
                        if rts != "default" else "default/queue",
                        "trial_dir": os.path.join(self.path, "data", f"{label}_{benchmark}_trial_{trial}"),
                        "container": f"fbpp-{self.name}-{i}", "running": False, "exit_code": None,
                        "ended": False})
        return out

    def _container_args(self, inst):
        fuzzer, benchmark = inst["fuzzer"], inst["benchmark"]
        args = ["run", "-d", "--name", inst["container"], *experiment_label(self.path), "--label", "fbpp.role=fuzz",
                f"--cpuset-cpus={inst['cpu']}", "-m", f"{self.memory}g", f"--memory-swap={self.memory}g",
                "-e", "RUNTIME=0",
                # Docker pins the container to its CPU. AFL++ would also bind itself to a CPU no other
                # afl-fuzz on the machine uses, and abort when every CPU has one (another experiment).
                "-e", "AFL_NO_AFFINITY=1",
                "-v", f"{os.path.join(self.path, 'benchmarks', f'{fuzzer}_{benchmark}')}:/benchmark",
                "-v", f"{os.path.join(self.path, 'fuzzers', fuzzer)}:/fuzzer",
                "-v", f"{inst['trial_dir']}:/fuzzer_output"]
        run_sh = os.path.join(self.project_root, "fuzzers", fuzzer, "run.sh")
        if os.path.isfile(run_sh):        # the current run.sh, which knows RUNTIME=0 means no limit
            args += ["-v", f"{run_sh}:/fuzzer/run.sh:ro"]
        if inst["configs"] is None:
            return args + ["fbpp/runner"]
        n = inst["rotation"]
        return args + ["-e", f"FUZZER_NAME={fuzzer}", "-e", f"CONFIG_INDEX={n}",
                       "-e", f"PREVIOUS={n - 1 if n > 0 else ''}",
                       "-v", f"{os.path.join(self.project_root, 'runtime')}:/runtime:ro",
                       "fbpp/runner", "bash", "/runtime/continuous_run.sh"]

    def _next_configuration(self, inst):
        """Moves a runtime-strategy instance to its next configuration (rotation n uses
        configs[n % len]), recorded as evaluation mode records them."""
        inst["rotation"] += 1
        n = inst["rotation"]
        configs = inst["configs"]
        path = os.path.join(inst["trial_dir"], "rt_configs.json")
        used = json.load(open(path))["configs"] if os.path.isfile(path) else []
        used.append(configs[n % len(configs)])
        with open(path + ".tmp", "w") as f:
            json.dump({"strategy": inst["rts"], "benchmark": inst["benchmark"], "trial": inst["trial"],
                       "mode": "continuous", "configs": used}, f, indent=1)
        os.replace(path + ".tmp", path)
        with open(os.path.join(inst["trial_dir"], "rt_run.jsonl"), "a") as f:
            f.write(json.dumps({"config": n, "args": configs[n % len(configs)], "configuration": n % len(configs),
                                "round": self.round, "started": self.clock()}) + "\n")
        link = os.path.join(inst["trial_dir"], "default")          # as multi_config_run.sh: the latest output
        if os.path.islink(link):
            os.remove(link)
        if not os.path.exists(link):
            os.symlink(f"config_{n}/default", link)

    def start(self, inst):
        os.makedirs(inst["trial_dir"], exist_ok=True)
        info = os.path.join(inst["trial_dir"], "trial_info.json")
        if not os.path.isfile(info):
            with open(info, "w") as f:
                json.dump({"fuzzer": inst["fuzzer"], "runtime_strategy": inst["rts"], "benchmark": inst["benchmark"],
                           "trial": inst["trial"], "mode": "continuous"}, f)
        if inst["configs"] is not None:
            self._next_configuration(inst)
        self.docker(["rm", "-f", inst["container"]])
        log_file = os.path.join(inst["trial_dir"], "fuzzing.log")
        result = self.docker(self._container_args(inst), log_file=log_file)
        inst["running"] = result.returncode == 0
        first = inst["rotation"] <= 0
        events.emit(self.path, "instance_start", run=inst["label"], benchmark=inst["benchmark"], trial=inst["trial"],
                    cpu=inst["cpu"], container=inst["container"], rotation=inst["rotation"], ok=inst["running"])
        if first:
            events.emit(self.path, "trial_start", run=inst["label"], benchmark=inst["benchmark"],
                        trial=inst["trial"], core=inst["cpu"])
        if not inst["running"]:
            self._ended(inst, "failure", f"could not start (see {log_file})")

    def stop(self, inst):
        self.docker(["rm", "-f", inst["container"]])
        inst["running"] = False

    def _ended(self, inst, status, reason=""):
        if inst["ended"]:
            return
        inst["ended"] = True
        inst["running"] = False
        events.emit(self.path, "trial_end", run=inst["label"], benchmark=inst["benchmark"], trial=inst["trial"],
                    core=inst["cpu"], status=status, reason=reason)

    def check(self):
        """Notices fuzzing containers that stopped on their own (the fuzzer exited or crashed)."""
        for inst in self.instances:
            if not inst["running"]:
                continue
            r = self.docker(["inspect", "-f", "{{.State.Running}} {{.State.ExitCode}}", inst["container"]])
            out = (r.stdout or "").split() if r.returncode == 0 else []
            if out and out[0] == "true":
                continue
            inst["exit_code"] = int(out[1]) if len(out) > 1 and out[1].lstrip("-").isdigit() else None
            self.log.error(f"Instance {inst['label']} on {inst['benchmark']}, trial {inst['trial']} stopped "
                           f"(exit code {inst['exit_code']}); see {inst['trial_dir']}/fuzzing.log")
            events.emit(self.path, "instance_exit", run=inst["label"], benchmark=inst["benchmark"],
                        trial=inst["trial"], exit_code=inst["exit_code"])
            self.docker(["logs", inst["container"]], log_file=os.path.join(inst["trial_dir"], "fuzzing.log"))
            self.docker(["rm", "-f", inst["container"]])
            self._ended(inst, "failure", f"the fuzzer exited with code {inst['exit_code']}")

    # --- Rounds ------------------------------------------------------------------------

    def _coverage(self, inst, cpu, min_age):
        coverage_build = os.path.join(self.path, "benchmarks", f"coverage_{inst['benchmark']}")
        args = ["run", "--rm", *experiment_label(self.path), "--label", "fbpp.role=coverage",
                f"--cpuset-cpus={cpu}", "-m", f"{self.memory}g", f"--memory-swap={self.memory}g",
                "-e", f"ROUND={self.round}", "-e", f"MIN_AGE={min_age}", "-e", f"OWNER={os.getuid()}:{os.getgid()}",
                "-e", f"FUZZER_NAME={inst['fuzzer']}", "-e", f"CORPUS_DIR={inst['corpus_dir']}"]
        for name in sorted(os.environ):           # settings of a fuzzer's coverage.py, as run_coverage passes them
            if name.startswith("VAFUZZ_COVERAGE_"):
                args += ["-e", name]
        args += ["-v", f"{coverage_build}:/benchmark:ro",
                 "-v", f"{os.path.join(self.path, 'fuzzers', inst['fuzzer'])}:/fuzzer:ro",
                 "-v", f"{os.path.join(self.project_root, 'runtime')}:/runtime:ro",
                 "-v", f"{inst['trial_dir']}:/fuzzer_output",
                 "fbpp/runner-coverage", "python3", "/runtime/continuous_coverage.py"]
        result = self.docker(args, log_file=os.path.join(inst["trial_dir"], "continuous_coverage.log"))
        return result.returncode == 0

    def _coverage_all(self, min_age):
        cpus = list(self.coverage_cpus)
        pool = list(cpus)           # one task per coverage CPU at a time (the executor's size)

        def task(inst):
            with self.lock:
                cpu = pool.pop()
            try:
                ok = self._coverage(inst, cpu, min_age)
            finally:
                with self.lock:
                    pool.append(cpu)
                if not ok:
                    self.log.error(f"Coverage round {self.round} failed for {inst['label']} on {inst['benchmark']}, "
                                   f"trial {inst['trial']}; see {inst['trial_dir']}/continuous_coverage.log")
                return ok
        with ThreadPoolExecutor(max_workers=len(cpus)) as executor:
            return list(executor.map(task, self.instances))

    def _snapshot(self, final):
        """Every trial's coverage after this round, as the statistics count it, into timeline.jsonl."""
        from statistical_analysis import load_trials
        trials = [{"arm": t["arm"], "benchmark": t["benchmark"], "trial": t["trial"], "copies": t["copies"],
                   "values": t["values"], "instrumented": t["instrumented"]} for t in load_trials(self.path)]
        new_inputs = 0
        for inst in self.instances:
            rounds = os.path.join(inst["trial_dir"], "continuous", "rounds.jsonl")
            try:
                last = json.loads(open(rounds).read().strip().splitlines()[-1])
                if last.get("round") == self.round:
                    new_inputs += last.get("new_inputs") or 0
            except (OSError, ValueError, IndexError):
                pass
        now = self.clock()
        record = {"round": self.round, "time": now, "elapsed": now - self.started, "final": final,
                  "new_inputs": new_inputs, "trials": trials}
        with open(os.path.join(campaign_dir(self.path), "timeline.jsonl"), "a") as f:
            f.write(json.dumps(record) + "\n")
        return record

    def _analyses(self):
        """The statistics report, SuperC and crash triage, as in evaluation mode, on the coverage CPUs."""
        from run_experiment import aggregate_results, run_superc_on_experiments, triage_on_experiments
        steps = [("aggregating", lambda: aggregate_results(self.state)),
                 ("statistics", self._statistics)]
        if not self.state.get("no_superc"):
            steps.insert(1, ("superc", lambda: run_superc_on_experiments(self.state, self.log, cpus=self.coverage_cpus)))
        if self.state.get("built_triagers"):
            steps.insert(-1, ("triage", lambda: triage_on_experiments(self.state, cpus=self.coverage_cpus)))
        for step, run in steps:
            events.emit(self.path, "round_step", round=self.round, step=step)
            self._write_status(step=step)
            try:
                run()
            except Exception as e:          # an analysis failing never stops the campaign
                self.log.error(f"Round {self.round}: {step} failed: {e}")

    def _statistics(self):
        from statistical_analysis import generate_statistics_report
        report_path = self.state.get("report_path") or os.path.join(self.state["report_filestore"], self.name)
        generate_statistics_report(self.path, os.path.join(report_path, "statistics"))

    def run_round(self, final=False):
        self.round += 1
        started = self.clock()
        self.log.info(f"Round {self.round}{' (last)' if final else ''}: coverage of {len(self.instances)} instance(s) "
                      f"on CPU(s) {self.coverage_cpus}")
        events.emit(self.path, "round_start", round=self.round, final=final)
        if not final:
            for inst in self.instances:            # runtime strategies: the next configuration
                if inst["configs"] is not None and inst["running"]:
                    self.stop(inst)
                    self.start(inst)
        self._write_status(step="coverage")
        results = self._coverage_all(0 if final else MIN_INPUT_AGE)
        record = self._snapshot(final)
        self._analyses()
        seconds = self.clock() - started
        events.emit(self.path, "round_end", round=self.round, final=final, seconds=round(seconds, 1),
                    new_inputs=record["new_inputs"], failed=results.count(False))
        self.log.info(f"Round {self.round} done in {seconds:.0f} s: {record['new_inputs']} new input(s)")
        self._write_status(step=None)

    # --- The campaign ------------------------------------------------------------------

    def _write_status(self, step=None):
        status = {"started": self.started, "round": self.round, "step": step, "next_round": self.next_round,
                  "interval": self.settings["interval"], "duration": self.settings["duration"],
                  "ends": self.started + self.settings["duration"] if self.settings["duration"] and self.started else None,
                  "stopping": self.stopping, "fuzz_cpus": self.fuzz_cpus, "coverage_cpus": self.coverage_cpus,
                  "updated": self.clock(),
                  "instances": [{k: inst[k] for k in ("label", "fuzzer", "rts", "benchmark", "trial", "cpu",
                                                      "container", "running", "exit_code", "rotation")}
                                for inst in self.instances]}
        path = os.path.join(campaign_dir(self.path), "status.json")
        with open(path + ".tmp", "w") as f:
            json.dump(status, f, indent=1)
        os.replace(path + ".tmp", path)

    def _control(self, what):
        path = os.path.join(campaign_dir(self.path), "control", what)
        if os.path.exists(path):
            if what == "round":
                os.remove(path)
            return True
        return False

    def run(self):
        interval, duration = self.settings["interval"], self.settings["duration"]
        self.started = self.clock()
        self.next_round = self.started + interval
        events.emit(self.path, "continuous", interval=interval, duration=duration, fuzz_cpus=self.fuzz_cpus,
                    coverage_cpus=self.coverage_cpus, instances=len(self.instances))
        self.log.info(f"Continuous campaign: {len(self.instances)} instance(s) on CPU(s) {self.fuzz_cpus}, coverage "
                      f"rounds every {interval} s on CPU(s) {self.coverage_cpus}"
                      + (f", for {duration} s" if duration else ", until stopped"))
        for inst in self.instances:
            self.start(inst)
        self._write_status()
        last_check = self.clock()
        while True:
            now = self.clock()
            if self._control("stop") or (duration and now >= self.started + duration):
                break
            if self._control("round") or now >= self.next_round:
                self.run_round()
                while self.next_round <= self.clock():     # a long round skips the rounds it overran
                    self.next_round += interval
                self._write_status()
            if self.clock() - last_check >= CHECK_SECONDS:
                self.check()
                last_check = self.clock()
                self._write_status()
            self.sleep(POLL_SECONDS)
        self.finish()

    def finish(self):
        """Stops every fuzzer, then a last round takes every input that is left."""
        self.stopping = True
        events.emit(self.path, "phase", phase="stopping")
        self.log.info("Stopping the campaign: fuzzers first, then a last coverage round")
        for inst in self.instances:
            if inst["running"]:
                self.stop(inst)
        self.next_round = None
        self.run_round(final=True)
        for inst in self.instances:
            self._ended(inst, "success")
        self._write_status()

    def kill_all(self):
        for inst in self.instances:
            if inst["running"]:
                self.stop(inst)


def run_campaign(state, logging=None):
    """Runs a continuous campaign to its end (see the module docstring)."""
    campaign = Campaign(state, logging)

    def terminate(signum, frame):          # the job was cancelled: stop the fuzzers, no last round
        raise SystemExit(128 + signum)
    previous = signal.signal(signal.SIGTERM, terminate)
    try:
        campaign.run()
    except BaseException:
        campaign.kill_all()
        raise
    finally:
        signal.signal(signal.SIGTERM, previous)
    return campaign


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Control a running continuous campaign.")
    parser.add_argument("action", choices=["stop", "round", "status"],
                        help="stop: stop after a last round; round: run a coverage round now; status: print it")
    parser.add_argument("experiment_path")
    args = parser.parse_args()
    if args.action == "status":
        print(json.dumps(read_status(args.experiment_path), indent=1))
        return
    request(args.experiment_path, args.action)
    print(f"Asked {args.experiment_path} to {'stop after a last round' if args.action == 'stop' else 'run a round now'}.")


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
