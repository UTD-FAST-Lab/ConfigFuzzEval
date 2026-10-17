"""Tests for common/interactive.py, with scripted answers instead of a terminal. Run from tests/:
    python3 -m unittest test_interactive
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "common"))

import interactive as ia


class ScriptedUI:
    """Answers questions in order; checks that ticked choices were offered and enabled."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.asked = []
        self.offered = {}

    def say(self, text=""):
        pass

    def _next(self, message):
        self.asked.append(message)
        return self.answers.pop(0)

    def text(self, message, default="", validate=None):
        answer = self._next(message)
        answer = str(default) if answer is None else answer
        if validate is not None:
            assert validate(answer) is True, f"{message} rejected {answer!r}"
        return answer

    def confirm(self, message, default=True):
        answer = self._next(message)
        return default if answer is None else answer

    def select(self, message, choices):
        answer = self._next(message)
        assert answer in [v for _, v in choices], f"{message}: {answer!r} not offered"
        return answer

    def checkbox(self, message, choices):
        self.offered[message] = {v: d for _, v, _, d in choices}
        answer = self._next(message)
        if answer is None:
            return [v for _, v, checked, _ in choices if checked]
        for value in answer:
            assert value in self.offered[message], f"{message}: {value!r} not offered"
            assert self.offered[message][value] is None, f"{message}: {value!r} is disabled"
        return answer


class StoresTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config = {"trials": 3, "max_total_time": 86400, "cores_to_use": 6,
                       "experiment_filestore": os.path.join(self.tmp.name, "exp"),
                       "report_filestore": os.path.join(self.tmp.name, "rep")}

    def tearDown(self):
        self.tmp.cleanup()


class AskTest(StoresTest):

    def test_same_benchmarks(self):
        ui = ScriptedUI([
            "same1",                                      # name
            True,                                         # same benchmarks
            ["default", "random", "zigzag"],              # strategies
            ["aflplusplus", "libafl"],                    # engines for default
            ["aflplusplus"],                              # engines for random
            ["binutils_objdump", "libxml2_xmllint"],      # benchmarks
            None,                                         # compile-time: default ticked
            "4",                                          # cores
            "2", "15m",                                   # trials, time
            True,                                         # superc
            ["gdb-exploitable"],                          # triaging
        ])
        experiment = ia.ask_experiment(ui, self.config)
        self.assertEqual(ui.answers, [])
        self.assertEqual([(g["fuzzers"], g["runtime_strategy"]) for g in experiment["groups"]],
                         [(["aflplusplus"], ["default"]), (["libafl"], ["default"]),
                          (["aflplusplus"], ["random"]), (["zigzagfuzz"], ["default"])])
        for group in experiment["groups"]:
            self.assertEqual(group["benchmarks"], ["binutils_objdump", "libxml2_xmllint"])
            self.assertEqual((group["compiletime"], group["trials"], group["max_total_time"]), (["default"], 2, 900))
        self.assertEqual(experiment["cores_to_use"], 4)
        # SuperC and triage are applied.
        self.assertEqual((experiment["no_superc"], experiment["bug_triaging"]), (False, ["gdb-exploitable"]))
        self.assertNotIn("not_applied", experiment)
        # zigzag has one engine, so it is not asked.
        self.assertFalse(any("zigzag" in m for m in ui.asked))

    def test_different_benchmarks_with_own_trials(self):
        ui = ScriptedUI([
            "diff1", False,
            ["carpet", "variability aware"],
            ["binutils_objdump"], ["default", "maximum"],     # carpetfuzz
            ["libxml2_xmllint"], None,                        # vafuzz
            None,                                             # cores from config
            False,                                            # not the same trials and time
            "1", "1h", "5", "24h",
            False, None,
        ])
        experiment = ia.ask_experiment(ui, self.config)
        self.assertEqual(ui.answers, [])
        carpet, vafuzz = experiment["groups"]
        self.assertEqual((carpet["fuzzers"], carpet["benchmarks"], carpet["compiletime"], carpet["trials"],
                          carpet["max_total_time"]), (["carpetfuzz"], ["binutils_objdump"], ["default", "maximum"], 1, 3600))
        self.assertEqual((vafuzz["fuzzers"], vafuzz["benchmarks"], vafuzz["trials"], vafuzz["max_total_time"]),
                         (["vafuzz"], ["libxml2_xmllint"], 5, 86400))
        self.assertEqual((experiment["no_superc"], experiment["bug_triaging"]), (True, []))

    def test_benchmarks_a_choice_cannot_run_are_disabled(self):
        ui = ScriptedUI(["dis1", True, ["carpet"], ["binutils_objdump"], None, None, None, None, False, None])
        ia.ask_experiment(ui, self.config)
        offered = ui.offered["Benchmarks:"]
        for benchmark, reason in offered.items():
            expected = ia.run_problems("carpetfuzz", benchmark, "default")
            self.assertEqual(reason is None, not expected, benchmark)

    def test_existing_name_is_asked_again(self):
        os.makedirs(os.path.join(self.config["report_filestore"], "taken"))
        ui = ScriptedUI(["taken", "fresh"])
        self.assertEqual(ia.ask_name(ui, self.config), "fresh")

    def test_bad_name_is_rejected(self):
        with self.assertRaises(AssertionError):
            ia.ask_name(ScriptedUI(["../x"]), self.config)


class FileTest(StoresTest):

    def test_saved_file_loads_and_expands(self):
        from experiment_plan import load_experiment_file, expand_groups
        experiment = {"experiment_name": "e", "cores_to_use": 2, "no_superc": True, "bug_triaging": [],
                      "not_applied": {"superc": True},
                      "groups": [{"fuzzers": ["aflplusplus"], "benchmarks": ["xz_xz"], "compiletime": ["default"],
                                  "runtime_strategy": ["random"], "trials": 2, "max_total_time": 900}]}
        path = os.path.join(self.tmp.name, "experiments", "e.yaml")
        ia.write_experiment(experiment, path)
        loaded = load_experiment_file(path)
        self.assertEqual(loaded["cores_to_use"], 2)
        runs = expand_groups(loaded["groups"], self.config)
        self.assertEqual([(r["fuzzer"], r["runtime_strategy"], r["trials"]) for r in runs], [("aflplusplus", "random", 2)])


class MainTest(StoresTest):
    """main() from the config question to the final choice, with the dry run and the launch replaced."""

    def answers(self, action):
        import yaml
        config_path = os.path.join(self.tmp.name, "config.yaml")
        with open(config_path, "w") as f:
            yaml.safe_dump(self.config, f)
        return [os.path.relpath(config_path), "main1", True, ["zigzag"], ["binutils_objdump"],
                None, None, None, None, False, None, action]

    def run_main(self, action, dry_run_code=0, extra=()):
        from unittest import mock
        ui = ScriptedUI(self.answers(action) + list(extra))
        saved = os.path.join(self.tmp.name, "experiments", "main1.yaml")
        dry_run = mock.Mock(returncode=dry_run_code)
        queued = mock.Mock(return_value=(7, saved, os.path.join(self.tmp.name, "experiments", "logs", "main1.log")))
        with mock.patch.object(ia, "PROJECT_ROOT", self.tmp.name), \
                mock.patch.object(ia.experiment_plan, "EXPERIMENTS_DIR", os.path.join(self.tmp.name, "experiments")), \
                mock.patch.object(ia, "queued_names", return_value=set()), \
                mock.patch.object(ia.jobs, "queue_experiment", queued), \
                mock.patch.object(ia.jobs, "queue", mock.Mock()), \
                mock.patch.object(ia.jobs, "queue_message", return_value="it starts now."), \
                mock.patch.object(ia, "strategies", return_value=[("zigzag", "", [("zigzagfuzz", "zigzagfuzz", "default")])]), \
                mock.patch.object(ia, "available_benchmarks", return_value=["binutils_objdump"]), \
                mock.patch.object(ia, "available_compiletime", return_value=["default"]), \
                mock.patch.object(ia, "available_triagers", return_value=[]), \
                mock.patch.object(ia, "run_problems", return_value=[]), \
                mock.patch.object(ia.subprocess, "run", return_value=dry_run) as run, \
                mock.patch.object(ia.subprocess, "Popen") as popen:
            code = ia.main(ui)
        self.queued = queued
        return code, saved, run, popen

    def test_save_keeps_the_file_and_dry_runs_it(self):
        code, saved, run, popen = self.run_main("save")
        self.assertEqual(code, 0)
        self.assertTrue(os.path.exists(saved))
        command = run.call_args[0][0]
        self.assertEqual(command[-1], "--dry-run")
        self.assertTrue(os.path.isabs(command[command.index("--config") + 1]))
        popen.assert_not_called()

    def test_save_does_not_queue(self):
        self.run_main("save")
        self.queued.assert_not_called()

    def test_cancel_deletes_the_file(self):
        code, saved, _, popen = self.run_main("cancel")
        self.assertEqual(code, 0)
        self.assertFalse(os.path.exists(saved))
        popen.assert_not_called()

    def test_queue_adds_it_to_the_shared_queue(self):
        code, saved, _, popen = self.run_main("queue", extra=[False])    # do not follow the log
        self.assertEqual(code, 0)
        config_path, experiment, _ = self.queued.call_args[0]
        self.assertTrue(os.path.isabs(config_path))
        self.assertEqual(experiment["experiment_name"], "main1")
        popen.assert_not_called()

    def test_failed_dry_run_stops_before_the_choice(self):
        code, saved, _, popen = self.run_main("save", dry_run_code=1)
        self.assertEqual(code, 1)
        self.assertTrue(os.path.exists(saved))
        popen.assert_not_called()


class HelpersTest(unittest.TestCase):

    def test_durations(self):
        self.assertEqual([ia.parse_duration(t) for t in ["900", "15m", "24h", "1h30m", "2d"]],
                         [900, 900, 86400, 5400, 172800])
        self.assertEqual(ia.format_duration(5400), "1h30m")
        with self.assertRaises(ValueError):
            ia.parse_duration("soon")

    def test_strategies(self):
        table = {name: engines for name, _, engines in ia.strategies()}
        self.assertEqual(table["default"], [("aflplusplus", "aflplusplus", "default"), ("libafl", "libafl", "default")])
        self.assertEqual(table["prophet"], [("carpetfuzz", "prophetfuzz", "default")])
        self.assertEqual(table["variability aware"], [("aflplusplus", "vafuzz", "default")])
        self.assertEqual(table["config based"], [("aflplusplus", "configfuzz", "default")])
        self.assertEqual([e for e, _, _ in table["random"]], ["aflplusplus", "libafl"])


if __name__ == "__main__":
    unittest.main()
