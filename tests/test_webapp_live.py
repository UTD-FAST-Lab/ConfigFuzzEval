"""The web app's Live tab: reading a trial's fuzzer_stats and plot_data, as an AFL++ 4.21a container prints them."""
import os
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "common"))
sys.path.insert(0, os.path.join(ROOT, "webapp"))

import live_view

PROBE_OUTPUT = """@now 1792662328
@dir /fuzzer_output/default
@mtime 1792662312
@stats
start_time        : 12389601
last_update       : 12390202
run_time          : 600
cycles_done       : 0
execs_done        : 1464202
execs_per_sec     : 2436.54
execs_ps_last_min : 2447.01
corpus_count      : 3229
corpus_favored    : 579
pending_favs      : 443
pending_total     : 3005
stability         : 100.00%
bitmap_cvg        : 19.13%
saved_crashes     : 2
saved_hangs       : 0
last_find         : 12390190
last_crash        : 12390000
edges_found       : 3209
total_edges       : 16774
afl_version       : ++4.21a
command_line      : /fuzzer/afl-fuzz -i /benchmark/seed -o /fuzzer_output /benchmark/pcre2test @@
@plot
# relative_time, cycles_done, cur_item, corpus_count, pending_total, pending_favs, map_size, saved_crashes, saved_hangs, max_depth, execs_per_sec, total_execs, edges_found
61, 0, 458, 812, 791, 192, 9.97%, 0, 0, 7, 2383.46, 154855, 1672
300, 0, 1200, 2100, 2000, 300, 15.10%, 1, 0, 10, 2401.00, 700000, 2600
600, 0, 3167, 3229, 3005, 443, 19.13%, 2, 0, 14, 2447.01, 1464202, 3209
@crashes
id:000000,sig:06,src:000123,time:4000,execs:9000,op:havoc,rep:2
id:000001,sig:11,src:000456,time:9000,execs:20000,op:havoc,rep:4
@ps
bash -c fuzzer/run.sh
/fuzzer/afl-fuzz -i /benchmark/seed -o /fuzzer_output /benchmark/pcre2test @@
/benchmark/pcre2test /fuzzer_output/default/.cur_input
"""


def test_parse_probe():
    p = live_view.parse_probe(PROBE_OUTPUT)
    assert p["now"] == 1792662328 and p["mtime"] == 1792662312 and p["dir"] == "/fuzzer_output/default"
    assert p["stats"]["afl_version"] == "++4.21a"
    assert p["stats"]["command_line"].endswith("pcre2test @@")      # a value with colons and spaces stays whole
    assert len(p["plot"]) == 4 and len(p["crashes"]) == 2
    assert live_view.stage(p) == "fuzzing"


def test_summary():
    s = live_view.summary(live_view.parse_probe(PROBE_OUTPUT))
    assert s["execs_per_sec"] == 2447.01                # the last minute's rate, not the run's average
    assert s["bitmap_cvg"] == 19.13 and s["stability"] == 100.0
    assert s["edges_found"] == 3209 and s["saved_crashes"] == 2
    # last_find is 12 s before last_update on AFL++'s clock, and the file was written 16 s ago.
    assert s["last_find_ago"] == 12 + 16 and s["last_crash_ago"] == 202 + 16


def test_series():
    rows = live_view.parse_probe(PROBE_OUTPUT)["plot"]
    s = live_view.series(rows)
    assert s["t"] == [61, 300, 600] and s["edges_found"] == [1672, 2600, 3209]
    assert s["execs_per_sec"][-1] == 2447.01 and s["saved_crashes"] == [0, 1, 2]
    many = [rows[0]] + [f"{t}, 0, 0, {t}, 0, 0, 1.00%, 0, 0, 1, 100.0, {t}, {t}" for t in range(1000)]
    thin = live_view.series(many, points=50)
    assert len(thin["t"]) == 50 and thin["t"][0] == 0 and thin["t"][-1] == 999   # thinned, keeping the latest row


def test_without_fuzzer_stats():
    p = live_view.parse_probe("@now 5\n@ps\nbash\npython3 /fuzzer/coverage.py\n")
    assert live_view.summary(p) is None and live_view.series(p["plot"]) == {}
    assert live_view.stage(p) == "coverage"


def test_trial_folder_is_checked(tmp_path):
    cfg = {"experiment_filestore": str(tmp_path)}
    (tmp_path / "e1" / "data" / "a_trial_0").mkdir(parents=True)
    for bad in ("../e1", "a/../../x", "", "a b"):
        assert live_view.trial(cfg, "e1", bad, running=False) is None
    assert live_view.trial(cfg, "e1", "missing_trial_0", running=False) is None
