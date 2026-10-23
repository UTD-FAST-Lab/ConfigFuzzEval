"""The web app's Crash triage tab: an experiment's triage results, counted as the statistics report counts them."""
import json
import os
import sqlite3
import sys
import tempfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "common"))
sys.path.insert(0, os.path.join(ROOT, "webapp"))

import statistical_analysis
import triage_view


def pool(root, triager, fuzzer, rts, copy, crashes, bug_files=None):
    """A pooled folder as the triagers write it; crashes: [(sample, hash)], hash None when it did not crash again."""
    label = fuzzer if rts == "default" else f"{fuzzer}_rts_{rts}"
    out = os.path.join(root, "bug-triaging", triager, "output", f"{label}_{copy}")
    os.makedirs(out)
    with open(os.path.join(out, "pool.json"), "w") as f:
        json.dump({"triager": triager, "fuzzer": fuzzer, "runtime_strategy": rts, "benchmark": copy, "trials": [0, 1]}, f)
    for k in (0, 1):
        open(os.path.join(out, f"trial_{k}.log"), "w").write("[triage] ...\n")
    con = sqlite3.connect(os.path.join(out, "crashes.db"))
    con.execute("CREATE TABLE Data (Sample TEXT PRIMARY KEY NOT NULL, Classification TEXT NOT NULL, "
                "Classification_Description TEXT NOT NULL, Hash TEXT, User_Comment TEXT)")
    for sample, h in crashes:
        con.execute("INSERT INTO Data VALUES (?, ?, ?, ?, ?)", (sample, "EXPLOITABLE" if h else "NOT_REPRODUCED", "", h, ""))
    con.commit()
    con.close()
    for key, files in (bug_files or {}).items():
        os.makedirs(os.path.join(out, "bugs", key))
        for name, text in files.items():
            open(os.path.join(out, "bugs", key, name), "w").write(text)


def test_counts_bugs_as_the_report_and_lists_each_bug():
    with tempfile.TemporaryDirectory() as exp:
        # two compile-time copies of one strategy: their bugs are combined into one arm
        pool(exp, "gdb-exploitable", "aflplusplus", "default", "cts_pairwise_xz_xz_0",
             [("trial_0/id:0", "aaaa"), ("trial_1/id:0", "aaaa"), ("trial_1/id:1", None)],
             {"aaaa": {"crash_state.txt": "SIGSEGV\nf\ng\nh\n", "command.txt": "/benchmark/xz -d -c /tmp/in\n"}})
        pool(exp, "gdb-exploitable", "aflplusplus", "default", "cts_pairwise_xz_xz_1", [("trial_0/id:0", "bbbb")])
        pool(exp, "gdb-exploitable", "aflplusplus", "random", "cts_default_xz_xz_0", [("trial_0/id:0", "aaaa")])
        pool(exp, "afl-collect", "aflplusplus", "random", "cts_default_xz_xz_0", [("trial_0:id:0", "m1.x"), ("trial_0:id:1", "m1.y")])
        d = triage_view.summary(exp)
        assert d["ok"] and d["triagers"] == ["afl-collect", "gdb-exploitable"]
        g = d["counts"]["gdb-exploitable"]["xz_xz"]
        assert g == {"aflplusplus{cts:pairwise}": 2, "aflplusplus[random]": 1, "union": 2}
        assert d["counts"]["afl-collect"]["xz_xz"] == {"aflplusplus[random]": 1, "union": 1}   # major hash only
        report = statistical_analysis.found_bugs(exp)
        for triager, per in report.items():
            for (arm, bench), bugs in per.items():
                assert d["counts"][triager][bench][arm] == len(bugs)
        first = next(t for t in d["tasks"] if t["copy"] == "cts_pairwise_xz_xz_0" and t["triager"] == "gdb-exploitable")
        assert (first["crashes"], first["reproduced"], first["bugs"]) == (3, 2, 1)
        assert len(first["logs"]) == 2
        bug = next(b for b in d["bugs"] if b["triager"] == "gdb-exploitable" and b["key"] == "aaaa")
        assert bug["arms"] == {"aflplusplus{cts:pairwise}": 2, "aflplusplus[random]": 1}
        assert bug["state"].startswith("SIGSEGV") and bug["command"].startswith("/benchmark/xz")
        assert bug["files"] == ["crash_state.txt", "command.txt"]


def test_no_triage():
    with tempfile.TemporaryDirectory() as exp:
        assert triage_view.summary(exp)["ok"] is False
