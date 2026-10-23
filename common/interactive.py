"""Interactive setup: `python3 common/run_experiment.py` with no flags.

Asks what to run, one question at a time with arrow-key menus (questionary),
saves the answers as an experiment file, experiments/<name>.yaml, checks it with
a dry run and then adds it to the job queue (common/jobs.py, shared with the web app),
where it runs in the background, or only keeps the file. The saved file runs the same
experiment again with `run_experiment.py --config CONFIG --experiment experiments/<name>.yaml`.

It asks for the same four things as the command line and the web app: fuzzers,
runtime strategies, benchmarks and compile-time strategies. Runtime strategies apply
to the config-agnostic fuzzers (runtime/supported_fuzzers.json); a config-aware
fuzzer chooses its own options, so it runs with the default runtime strategy.

What can run comes from webapp/catalog.py, the same rules the web app and
validation.validate_runs use; runs are named like statistical_analysis.arm_name.

SuperC and bug triaging are asked and applied.
"""

import os
import re
import subprocess
import sys

import yaml

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "webapp"))

import catalog
import experiment_plan
import jobs
from experiments import valid_name
from statistical_analysis import arm_name

# Shown next to the fuzzers in fuzzers/; a fuzzer without an entry is listed by its name.
FUZZER_DESCRIPTIONS = {
    "aflplusplus": "AFL++",
    "libafl": "LibAFL",
    "carpetfuzz": "CarpetFuzz: option combinations mined from the man page",
    "prophetfuzz": "ProphetFuzz: option combinations predicted by an LLM",
    "vafuzz": "VAFuzz: each input under a batch of option configurations",
    "configfuzz": "ConfigFuzz: options encoded in the first bytes of each input",
    "zigzagfuzz": "ZigZagFuzz: fuzzes the input and the command line together",
}
RUNTIME_DESCRIPTIONS = {
    "default": "the benchmark's fixed command line",
    "smartrandom": "50 random valid option configurations",
    "pairwise": "a 2-way covering array of the options",
    "diversity": "50 configurations as different from each other as possible",
    "mostenabled": "one configuration with as many options on as possible",
    "mostdisabled": "one configuration with every option off",
}
# Compile-time strategies that build more than one copy of a benchmark.
MANY_COPIES = {"pairwise", "smartrandom"}


class Cancelled(Exception):
    pass


_catalog = None


def get_catalog():
    """What the repository offers to run (webapp/catalog.py), read once."""
    global _catalog
    if _catalog is None:
        _catalog = catalog.load(PROJECT_ROOT)
    return _catalog


def run_problems(fuzzer, benchmark, rts):
    return catalog.problems(get_catalog(), fuzzer, benchmark, rts)


def available_benchmarks():
    return sorted(get_catalog()["benchmarks"])


def available_compiletime():
    return sorted(get_catalog()["compiletime"])


def available_triagers():
    return sorted(get_catalog()["triagers"])


def available_fuzzers():
    return sorted(get_catalog()["fuzzers"])


def available_runtime():
    order = list(RUNTIME_DESCRIPTIONS)
    return sorted(get_catalog()["runtime"], key=lambda r: (order.index(r) if r in order else len(order), r))


def takes_runtime_strategies(fuzzer):
    """Config-agnostic: listed in runtime/supported_fuzzers.json, with a run.sh that reads $SEED_DIR."""
    return get_catalog()["fuzzers"].get(fuzzer, {}).get("runtime_strategies", False)


def label(fuzzer, rts):
    """How the statistics report names a run (an arm): fuzzer[rts], or the fuzzer for default."""
    return arm_name(fuzzer, rts, "default")


def parse_duration(text):
    """Seconds from '900', '15m', '24h', '1h30m' or '2d'."""
    text = str(text).strip().lower().replace(" ", "")
    if text.isdigit():
        return int(text)
    parts = re.fullmatch(r"(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?", text)
    if not text or not parts:
        raise ValueError(f"not a duration: {text!r} (examples: 900, 15m, 24h, 1h30m)")
    d, h, m, s = (int(x or 0) for x in parts.groups())
    return d * 86400 + h * 3600 + m * 60 + s


def format_duration(seconds):
    out = ""
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60), ("s", 1)):
        if seconds >= size:
            out += f"{seconds // size}{unit}"
            seconds %= size
    return out or "0s"


def _positive(text, upper=None):
    try:
        value = int(text)
    except ValueError:
        return "enter a whole number"
    if value <= 0:
        return "must be at least 1"
    if upper is not None and value > upper:
        return f"at most {upper}"
    return True


def _duration_ok(text):
    try:
        return True if parse_duration(text) > 0 else "must be longer than 0"
    except ValueError as e:
        return str(e)


class QuestionaryUI:
    """The questions, asked with questionary; tests replace it with scripted answers."""

    def __init__(self):
        import questionary
        self.q = questionary
        self.style = questionary.Style([("disabled", "fg:#858585 italic")])

    def _ask(self, question):
        answer = question.unsafe_ask()     # Ctrl-C raises KeyboardInterrupt instead of returning None
        return answer

    def say(self, text=""):
        print(text)

    def text(self, message, default="", validate=None):
        return self._ask(self.q.text(message, default=str(default), validate=validate, style=self.style)).strip()

    def confirm(self, message, default=True):
        return self._ask(self.q.confirm(message, default=default, style=self.style))

    def select(self, message, choices):
        """choices: [(title, value)]; returns the chosen value."""
        return self._ask(self.q.select(message, [self.q.Choice(t, v) for t, v in choices], style=self.style))

    def checkbox(self, message, choices):
        """choices: [(title, value, checked, disabled reason or None)]; returns the ticked values, at least one."""
        return self._ask(self.q.checkbox(
            message, [self.q.Choice(t, v, checked=c, disabled=d) for t, v, c, d in choices],
            validate=lambda ticked: True if ticked else "tick at least one (space ticks, enter continues)",
            instruction="(space to tick, a for all, enter to continue)", style=self.style))


def queued_names(config):
    try:
        return jobs.queue(config).active_names()
    except Exception:            # no queue yet, or it cannot be read: the queue checks again
        return set()


def ask_name(ui, config):
    """A new experiment name: one folder name, not in the result folders or the queue yet."""
    stores = [config["experiment_filestore"], config["report_filestore"]]
    while True:
        name = ui.text("Experiment name:", validate=lambda t: True if valid_name(t.strip())
                       else "letters, digits, '.', '_' and '-' only, starting with a letter or digit")
        taken = [s for s in stores if os.path.exists(os.path.join(s, name))]
        if not taken and name not in queued_names(config):
            return name
        ui.say(f"  {name} already exists in {' and '.join(taken)}; choose another name." if taken else
               f"  {name} is already queued or running; choose another name.")


def ask_fuzzers(ui):
    def title(fuzzer):
        kind = "config-agnostic" if takes_runtime_strategies(fuzzer) else "config-aware"
        return f"{fuzzer:<12} {kind:<16} {FUZZER_DESCRIPTIONS.get(fuzzer, '')}".rstrip()
    return ui.checkbox("Fuzzers:", [(title(f), f, False, None) for f in available_fuzzers()])


def ask_runtime(ui, fuzzers):
    """The runtime strategies of each fuzzer: [(fuzzer, [rts])]. Only config-agnostic fuzzers are asked;
    the others run with default."""
    agnostic = [f for f in fuzzers if takes_runtime_strategies(f)]
    chosen = ["default"]
    if agnostic:
        chosen = ui.checkbox(f"Runtime strategies (for {', '.join(agnostic)}):",
                             [(f"{r:<13} {RUNTIME_DESCRIPTIONS.get(r, '')}".rstrip(), r, r == "default", None)
                              for r in available_runtime()])
    aware = [f for f in fuzzers if f not in agnostic]
    if aware and chosen != ["default"]:
        ui.say(f"  {', '.join(aware)}: config-aware (chooses its own options), so only the default runtime strategy.")
    return [(f, chosen if f in agnostic else ["default"]) for f in fuzzers]


def ask_benchmarks(ui, message, selections):
    """Benchmarks every (fuzzer, runtime strategies) selection can run on; the others are listed but
    cannot be ticked."""
    choices = []
    for benchmark in available_benchmarks():
        reasons = [f"{label(f, r)}: {reason}" for f, strategies in selections for r in strategies
                   for reason in run_problems(f, benchmark, r)]
        choices.append((benchmark, benchmark, False, reasons[0] if reasons else None))
    if all(c[3] for c in choices):
        raise Cancelled(f"no benchmark can run {', '.join(label(f, r) for f, rs in selections for r in rs)}")
    return ui.checkbox(message, choices)


def ask_compiletime(ui, message):
    return ui.checkbox(message, [(ct + ("  (builds many copies of each benchmark)" if ct in MANY_COPIES else ""),
                                  ct, ct == "default", None) for ct in available_compiletime()])


def ask_trials_and_time(ui, config, what=""):
    trials = int(ui.text(f"Trials per run{what}:", config["trials"], validate=_positive))
    time = parse_duration(ui.text(f"Fuzzing time per trial{what} (e.g. 900, 15m, 24h):",
                                  format_duration(config["max_total_time"]), validate=_duration_ok))
    return trials, time


def ask_experiment(ui, config):
    """Ask every question; returns the experiment file as a dict."""
    name = ask_name(ui, config)
    same = ui.select("Benchmarks:", [("Same benchmarks for the whole experiment", True),
                                     ("Different benchmarks for different fuzzers", False)])
    selections = ask_runtime(ui, ask_fuzzers(ui))

    groups = []
    if same:
        benchmarks = ask_benchmarks(ui, "Benchmarks:", selections)
        compiletime = ask_compiletime(ui, "Compile-time strategies:")
        for fuzzer, rts in selections:
            groups.append({"fuzzers": [fuzzer], "benchmarks": benchmarks,
                           "compiletime": compiletime, "runtime_strategy": rts})
    else:
        for selection in selections:
            fuzzer, rts = selection
            benchmarks = ask_benchmarks(ui, f"Benchmarks for {fuzzer}:", [selection])
            compiletime = ask_compiletime(ui, f"Compile-time strategies for {fuzzer}:")
            groups.append({"fuzzers": [fuzzer], "benchmarks": benchmarks,
                           "compiletime": compiletime, "runtime_strategy": rts})

    cores = int(ui.text("Cores to use:", config["cores_to_use"],
                        validate=lambda t: _positive(t, os.cpu_count())))
    if len(groups) > 1 and not same and not ui.confirm("Same trials and fuzzing time for every fuzzer?"):
        for group in groups:
            group["trials"], group["max_total_time"] = ask_trials_and_time(
                ui, config, f" of {group['fuzzers'][0]}")
    else:
        trials, time = ask_trials_and_time(ui, config)
        for group in groups:
            group["trials"], group["max_total_time"] = trials, time

    superc = ui.confirm("Run the SuperC presence-condition analysis at the end (which #if conditions "
                        "the trials covered)?", default=False)
    triagers = available_triagers()
    triaging = ui.checkbox("Bug triaging:", [("none", "", True, None)] +
                           [(t, t, False, None) for t in triagers])
    triaging = [t for t in triaging if t]

    return {"experiment_name": name, "cores_to_use": cores,
            "no_superc": not superc, "bug_triaging": triaging,
            "groups": groups}


def write_experiment(experiment, path):
    experiment_plan.write_experiment_file(path, experiment)


def run_experiment_command(config_path, experiment_path, *extra):
    return [sys.executable, os.path.join(PROJECT_ROOT, "common", "run_experiment.py"),
            "--config", config_path, "--experiment", experiment_path, *extra]


def main(ui=None):
    if ui is None:
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            print("run_experiment.py with no flags asks what to run, which needs a terminal. "
                  "Give --config and --experiment (or --fuzzers/--benchmarks) instead; see --help.",
                  file=sys.stderr)
            return 2
        try:
            ui = QuestionaryUI()
        except ImportError:
            print("The interactive setup needs questionary: pip install -r requirements.txt", file=sys.stderr)
            return 2

    saved = None
    try:
        config_path = ui.text("Config file (machine settings, default trials and time):",
                              os.path.relpath(os.path.join(PROJECT_ROOT, "config.yaml")),
                              validate=lambda t: True if os.path.isfile(t.strip()) else "no such file")
        config_path = os.path.abspath(config_path)     # the background run starts in PROJECT_ROOT
        with open(config_path) as f:
            config = yaml.safe_load(f)

        experiment = ask_experiment(ui, config)
        saved = experiment_plan.saved_experiment_path(experiment["experiment_name"])
        if os.path.exists(saved) and not ui.confirm(f"{os.path.relpath(saved)} exists; replace it?", default=False):
            raise Cancelled("kept the existing experiment file")
        write_experiment(experiment, saved)

        ui.say(f"\nSaved {os.path.relpath(saved)}. Checking it with a dry run (nothing is built or run):")
        if subprocess.run(run_experiment_command(config_path, saved, "--dry-run")).returncode != 0:
            ui.say(f"\nThe dry run failed; {os.path.relpath(saved)} is saved, fix it and run it with --experiment.")
            return 1

        action = ui.select("What now?", [("Add it to the queue: it runs in the background, also after "
                                          "this terminal is closed", "queue"),
                                         ("Only keep the experiment file", "save"),
                                         ("Cancel and delete the experiment file", "cancel")])
    except (KeyboardInterrupt, Cancelled) as e:
        ui.say(f"\nCancelled{': ' + str(e) if isinstance(e, Cancelled) and str(e) else ''}.")
        return 130 if isinstance(e, KeyboardInterrupt) else 1

    rerun = " ".join(os.path.relpath(a) if os.path.isabs(a) else a
                     for a in run_experiment_command(config_path, saved)[1:])
    if action == "cancel":
        os.remove(saved)
        ui.say(f"Deleted {os.path.relpath(saved)}.")
        return 0
    if action == "save":
        ui.say(f"Saved {os.path.relpath(saved)}. Queue it with:\n  python3 {rerun}")
        return 0
    try:
        job_id, saved, log_path = jobs.queue_experiment(config_path, experiment, config)
    except ValueError as e:
        ui.say(str(e))
        return 1
    name = experiment["experiment_name"]
    ui.say(f"\nQueued {name} (job {job_id}); {jobs.queue_message(jobs.queue(config), job_id)}"
           + f"\n  Experiment file: {os.path.relpath(saved)}\n  Log:             {os.path.relpath(log_path)}"
           f"\n  Stop it:         {experiment_plan.stop_command(name)}")
    try:
        follow = ui.confirm("Follow the log now? (Ctrl-C stops following, not the experiment)", default=False)
    except KeyboardInterrupt:
        follow = False
    if follow:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        open(log_path, "a").close()
        os.execvp("tail", ["tail", "-F", log_path])
    return 0
