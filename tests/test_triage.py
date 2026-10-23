"""Tests for bug-triaging/gdb-exploitable/triage.py (the command line of every crash, no gdb or
Docker) and statistical_analysis.found_bugs."""
import importlib.util
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "common"))


def load_triage(tmp, fuzzer, run_target="/benchmark/prog -x @@"):
    out, bench = Path(tmp) / "out", Path(tmp) / "bench"
    (out / "default" / "crashes").mkdir(parents=True)
    bench.mkdir()
    (bench / "run_target.sh").write_text(run_target + "\n")
    os.environ.update(TRIAGE_OUT=str(out), TRIAGE_BENCHMARK=str(bench), TRIAGE_RESULTS=str(Path(tmp) / "res"),
                      FUZZER_NAME=fuzzer)
    sys.modules.pop("crash_commands", None)        # it reads the environment when imported
    spec = importlib.util.spec_from_file_location(f"triage_{fuzzer}", os.path.join(ROOT, "bug-triaging",
                                                                                   "gdb-exploitable", "triage.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, out


def test_plain_fuzzers_use_the_benchmark_command():
    with tempfile.TemporaryDirectory() as tmp:
        t, out = load_triage(tmp, "aflplusplus")
        crash = Path(tmp) / "c"
        assert t.commands("id:000000,sig:11", crash, out / "default", t.RUN_TARGET, Path(tmp)) == \
            [[["/benchmark/prog", "-x", str(crash)], None]]
    with tempfile.TemporaryDirectory() as tmp:
        t, out = load_triage(tmp, "libafl", "/benchmark/prog -")            # no @@: on stdin
        crash = Path(tmp) / "c"
        assert t.commands("id:000000", crash, out / "default", t.RUN_TARGET, Path(tmp)) == \
            [[["/benchmark/prog", "-"], crash]]


def test_zigzagfuzz_uses_the_saved_argv():
    with tempfile.TemporaryDirectory() as tmp:
        t, out = load_triage(tmp, "zigzagfuzz")
        (out / "default" / "crashes_argvs").mkdir()
        (out / "default" / "crashes_argvs" / "id:000003").write_bytes(b"--html\x00@@\x00@@\x00\x02\x00\x00tail")
        crash = Path(tmp) / "c"
        [[argv, stdin]] = t.commands("id:000003,sig:07,src:1", crash, out / "default", t.RUN_TARGET, Path(tmp))
        # only the first @@ is the input; 0x02 is an empty argument; the list ends at an empty word
        assert argv == ["/benchmark/prog", b"--html", os.fsencode(crash), b"@@", b""] and stdin is None


def test_carpetfuzz_uses_the_ranked_command_of_the_argv_tag():
    with tempfile.TemporaryDirectory() as tmp:
        t, out = load_triage(tmp, "carpetfuzz")
        (out / "ranked_stubs.txt").write_text("2\nprog -a @@\nprog -b -c @@\n")
        crash = Path(tmp) / "c"
        assert t.commands("id:000001,sig:11,src:000002,argv:000001,time:5", crash, out / "default", t.RUN_TARGET,
                          Path(tmp)) == [[["/benchmark/prog", "-b", "-c", str(crash)], None]]


def test_vafuzz_tries_every_configuration_it_crashed_under():
    with tempfile.TemporaryDirectory() as tmp:
        t, out = load_triage(tmp, "vafuzz")
        argvs = out / "default" / "crashes_argvs"
        argvs.mkdir()
        (argvs / "id:000000_2").write_text("-a -b")
        (argvs / "id:000000_5").write_text("-c")
        (argvs / "id:000001_0").write_text("-z")
        crash = Path(tmp) / "c"
        assert t.commands("id:000000,sig:11", crash, out / "default", t.RUN_TARGET, Path(tmp)) == [
            [["/benchmark/prog", "-a", "-b", "-x", str(crash)], None],
            [["/benchmark/prog", "-c", "-x", str(crash)], None]]


def test_runtime_strategy_trials_use_each_configurations_command():
    with tempfile.TemporaryDirectory() as tmp:
        t, out = load_triage(tmp, "aflplusplus")
        (out / "rt_configs.json").write_text(json.dumps({"configs": [["-a", "@@"], ["-b", "@@"]]}))
        (out / "rt_run.jsonl").write_text('{"config": 0}\n{"config": 1}\n')
        assert t.crash_dirs() == [("config_0", out / "config_0" / "default", "/benchmark/prog -a @@"),
                                  ("config_1", out / "config_1" / "default", "/benchmark/prog -b @@")]


def test_found_bugs_counts_crash_states_per_arm():
    from statistical_analysis import found_bugs
    with tempfile.TemporaryDirectory() as exp:
        for name, info, rows in [
            ("aflplusplus_rts_smartrandom_cts_default_xz_xz_0", {"fuzzer": "aflplusplus", "runtime_strategy": "smartrandom",
                                                             "benchmark": "cts_default_xz_xz_0"},
             [("a", "EXPLOITABLE", "x", "k1"), ("b", "EXPLOITABLE", "x", "k1"), ("c", "UNKNOWN", "x", "k2"),
              ("d", "NOT_REPRODUCED", "x", None)]),
            ("zigzagfuzz_cts_mostenabled_xz_xz_0", {"fuzzer": "zigzagfuzz", "runtime_strategy": "default",
                                                 "benchmark": "cts_mostenabled_xz_xz_0"},
             [("e", "EXPLOITABLE", "x", "k9")]),
        ]:
            pool = os.path.join(exp, "bug-triaging", "gdb-exploitable", "output", name)
            os.makedirs(pool)
            with open(os.path.join(pool, "pool.json"), "w") as f:
                json.dump(info, f)
            db = sqlite3.connect(os.path.join(pool, "crashes.db"))
            db.execute("CREATE TABLE Data (Sample TEXT PRIMARY KEY NOT NULL, Classification TEXT NOT NULL, "
                       "Classification_Description TEXT NOT NULL, Hash TEXT, User_Comment TEXT)")
            db.executemany("INSERT INTO Data VALUES (?, ?, ?, ?, '')", rows)
            db.commit()
            db.close()
        assert found_bugs(exp) == {"gdb-exploitable": {("aflplusplus[smartrandom]", "xz_xz"): {"k1", "k2"},
                                                       ("zigzagfuzz{cts:mostenabled}", "xz_xz"): {"k9"}}}


def test_crash_state_skips_library_frames_and_keeps_three():
    with tempfile.TemporaryDirectory() as tmp:
        t, _ = load_triage(tmp, "aflplusplus", "/benchmark/xmllint @@")
        output = "\n".join(["STACK_FRAME:r-xp /usr/lib/x86_64-linux-gnu/libc.so.6!__memmove_evex+0x0"] +
                            [f"STACK_FRAME:r-xp /benchmark/xmllint!{f}+0x0" for f in ("xmlMemRead", "grow", "parse", "main")])
        assert t.crash_state("SIGBUS", output) == "SIGBUS\nxmlMemRead\ngrow\nparse"
        assert t.printable([b"/b/x", b"--o\xff", "a b"]) == "/b/x '--o\\xff' 'a b'"


def test_run_experiment_script_runs_a_dry_run():
    """The script itself, not only its functions: it must parse its flags and print the plan."""
    import subprocess
    import yaml
    with tempfile.TemporaryDirectory() as tmp:
        config = {"trials": 1, "max_total_time": 60, "base_image_path": "docker/base-image",
                  "runner_image_path": "docker/runner-image", "experiment_filestore": os.path.join(tmp, "e"),
                  "report_filestore": os.path.join(tmp, "r"), "cores_to_use": 1, "allow_serial_execution": True,
                  "experiment_memory": 1024, "random_seed": 1, "serialize_multi_conf": False}
        with open(os.path.join(tmp, "config.yaml"), "w") as f:
            yaml.safe_dump(config, f)
        result = subprocess.run([sys.executable, os.path.join(ROOT, "common", "run_experiment.py"), "--config",
                                 os.path.join(tmp, "config.yaml"), "--experiment-name", "t", "--fuzzers", "aflplusplus",
                                 "--benchmarks", "xz_xz", "--bug-triaging", "gdb-exploitable", "--no-superc",
                                 "--dry-run"], capture_output=True, text=True, cwd=ROOT, timeout=300)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "Dry run of experiment t" in result.stdout and "bug triaging: ['gdb-exploitable']" in result.stdout


def test_afl_collect_launcher_finds_the_crash_name():
    sys.modules.pop("crash_commands", None)
    spec = importlib.util.spec_from_file_location("launcher", os.path.join(ROOT, "bug-triaging", "afl-collect",
                                                                           "launcher.py"))
    launcher = importlib.util.module_from_spec(spec)
    sys.path.insert(0, os.path.join(ROOT, "bug-triaging"))
    spec.loader.exec_module(launcher)
    assert launcher.crash_name("trial_0_config_2:id:000001,sig:11,argv:000003") == "id:000001,sig:11,argv:000003"
    assert launcher.crash_name("id:000001,sig:11") == "id:000001,sig:11"
