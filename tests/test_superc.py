"""Tests for common/superc.py (no Docker): conditions, trees, LCOV and their join."""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "common"))

import superc


def test_conditions_from_smt():
    assert superc.condition("(assert (or and))\n") == "1"
    assert superc.condition("(assert or)\n") == "0"
    assert superc.condition("(declare-fun |(defined X)| () Bool)\n(assert (or (and |(defined X)|)))\n") == "defined(X)"
    assert superc.condition("(assert (or (and (not |(defined X)|))))") == "!defined(X)"
    assert superc.condition("(assert (or (and A (not B)) (and C)))") == "(A && !B) || C"
    assert superc.condition("(assert (or (and A) (and A)))") == "A"
    assert superc.condition("") == "1"


def test_innermost_region_owns_its_lines():
    tree = {"StartLine": 0, "EndLine": 20, "PC": "(assert (or and))", "Sub": [
        [{"StartLine": 5, "EndLine": 10, "PC": "(assert (or (and A)))", "Sub": [
            [{"StartLine": 7, "EndLine": 8, "PC": "(assert (or (and A B)))", "Sub": []}]]}],
        [{"StartLine": 12, "EndLine": 13, "PC": "(assert or)", "Sub": []}]]}
    lines = superc.pc_lines(tree)
    assert lines["A"] == {5, 6, 9, 10}
    assert lines["A && B"] == {7, 8}
    assert lines["0"] == {12, 13}
    assert 7 not in lines["1"] and 0 in lines["1"]


def test_lcov_and_summary_keep_files_with_the_same_name_apart():
    with tempfile.TemporaryDirectory() as tmp:
        report = os.path.join(tmp, "report.json")
        with open(report, "w") as f:
            f.write("SF:/src/a/util.c\nDA:5,3\nDA:6,0\nDA:7,1\nend_of_record\n"
                    "SF:/src/b/util.c\nDA:5,0\nDA:6,0\nend_of_record\n")
        lcov = superc.parse_lcov(report)
    assert lcov["/src/a/util.c"] == ({5, 6, 7}, {5, 7})
    assert lcov["/src/b/util.c"] == ({5, 6}, set())
    pcs = {("A", "/src/a/util.c"): {5, 6}, ("A", "/src/b/util.c"): {5, 6}, ("B", "/src/a/util.c"): {9},
           ("1", "/src/a/util.c"): {7}}
    summary = superc.summarize(pcs, lcov)
    assert summary["A"]["instrumented_lines"] == 4 and summary["A"]["covered_lines"] == 1
    assert summary["B"]["instrumented_lines"] == 0          # not in this build
    counts = superc.coverage_counts(summary)
    assert counts == {"conditions": 2, "conditions_in_build": 1, "conditions_covered": 1,
                      "conditional_lines_in_build": 4, "conditional_lines_covered": 1}


def test_source_root_and_includes(tmp_path=None):
    assert superc.source_root(["/binutils-2.47/bfd/a.c", "/binutils-2.47/binutils/b.c", "/usr/include/x.h"]) == "/binutils-2.47"
    flags = superc.read_flags("binutils_objdump", "/binutils-2.47")
    assert ("-I", "/binutils-2.47/bfd") in flags and ("-I", "/binutils-2.47/include") in flags
    assert ("-D", "HAVE_CONFIG_H") in flags


def test_every_benchmark_has_valid_superc_flags():
    root = os.path.join(superc.PROJECT_ROOT, "benchmarks")
    benchmarks = [b for b in os.listdir(root) if not b.startswith("cts_")
                  and os.path.isfile(os.path.join(root, b, "builder.Dockerfile"))]
    assert benchmarks
    for b in benchmarks:
        assert os.path.isfile(os.path.join(root, b, "superc_flags.txt")), b
        superc.read_flags(b, "/src")          # raises on a malformed line


def test_load_pcs_keys_files_by_path():
    with tempfile.TemporaryDirectory() as out:
        for path in ("pc/src/a/util.c.json", "pc/src/b/util.c.json"):
            os.makedirs(os.path.dirname(os.path.join(out, path)), exist_ok=True)
            with open(os.path.join(out, path), "w") as f:
                json.dump({"StartLine": 0, "EndLine": 3, "PC": "(assert (or (and A)))", "Sub": []}, f)
        pcs = superc.load_pcs(out)
    assert set(pcs) == {("A", "/src/a/util.c"), ("A", "/src/b/util.c")}


def test_top_region_covers_the_file_up_to_a_block_superc_missed():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "a.c")
        with open(path, "w") as f:
            f.write("int a;\n#if X\nint b;\n#endif\nint c;\nint d;\n")      # 7 lines (last one empty)
        # SuperC's top region ends at line 1, before the #if X block it does report (lines 2-4).
        tree = {"StartLine": 0, "EndLine": 1, "PC": "(assert (or and))",
                "Sub": [[{"StartLine": 2, "EndLine": 4, "PC": "(assert (or (and X)))", "Sub": []}]]}
        extended, early = superc.extend_tree(tree, path)
        assert (extended["EndLine"], early) == (7, False)
        assert superc.pc_lines(extended)["1"] >= {5, 6} and superc.pc_lines(extended)["X"] == {2, 3, 4}
        # The same file without the reported block: SuperC stopped before #if X.
        stopped, early = superc.extend_tree({"StartLine": 0, "EndLine": 1, "PC": "", "Sub": []}, path)
        assert (stopped["EndLine"], early) == (1, True)


def test_directives_in_comments_are_not_blocks():
    text = "int a; /* x\n#if 0\n */\n// #ifdef Y\nchar *s = \"/* not a comment\";\n#if Z\n"
    stripped = superc.strip_comments(text).split("\n")
    assert len(stripped) == len(text.split("\n"))
    assert [n for n, l in enumerate(stripped, 1) if superc.CONDITIONAL_DIRECTIVE.match(l)] == [6]
