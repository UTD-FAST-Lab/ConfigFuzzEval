import math
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "common"))

import statistical_analysis as sa


def test_min_two_sided_p():
    assert math.isclose(sa.min_two_sided_p(3, 3), 0.1)
    assert math.isclose(sa.min_two_sided_p(5, 5), 2 / 252)


def test_mann_whitney_reaches_floor_and_handles_identical():
    assert math.isclose(sa.mann_whitney([1, 2, 3, 4, 5], [6, 7, 8, 9, 10]), 2 / 252)
    assert sa.mann_whitney([3, 3, 3], [3, 3, 3]) == 1.0


def test_holm():
    adjusted = sa.holm([0.01, 0.04, 0.03, 0.005])
    assert [round(p, 6) for p in adjusted] == [0.03, 0.06, 0.06, 0.02]
    assert math.isnan(sa.holm([float("nan"), 0.01])[0])


def test_a12():
    assert sa.a12([1, 2, 3], [1, 2, 3]) == 0.5
    assert sa.a12([4, 5], [1, 2]) == 1.0
    assert sa.a12([1, 2], [4, 5]) == 0.0


def test_nemenyi_cd_matches_demsar_table():
    # q_0.05 / sqrt(2) for k = 2..6 (Demsar 2006, table 5a)
    for k, q in zip(range(2, 7), (1.960, 2.343, 2.569, 2.728, 2.850)):
        assert math.isclose(sa.nemenyi_cd(k, 1) / math.sqrt(k * (k + 1) / 6), q, abs_tol=2e-3)


def test_dunn_without_ties():
    p = sa.dunn([[1, 2, 3, 4, 5], [6, 7, 8, 9, 10], [11, 12, 13, 14, 15]])
    # mean ranks 3, 8, 13; se = sqrt(15*16/12 * 2/5)
    z = 5 / math.sqrt(20 * 0.4)
    assert math.isclose(p[(0, 1)], 2 * sa.stats.norm.sf(z))


def test_cd_cliques():
    assert sa.cd_cliques(list("abcd"), [1, 1.5, 3, 3.2], 1.0) == [[0, 1], [2, 3]]
    assert sa.cd_cliques(list("abc"), [1, 2, 3], 5.0) == [[0, 1, 2]]


def test_parse_report_txt(tmp_path):
    report = tmp_path / "report.txt"
    report.write_text(
        "Filename Regions Missed Cover Functions Missed Executed Lines Missed Cover Branches Missed Cover\n"
        "TOTAL 49438 35625 27.94% 300 174 42.00% 30962 20620 33.40% 24934 17799 28.62%\n")
    totals = sa.parse_report_txt(str(report))
    assert totals == {"regions": (13813, 49438), "functions": (126, 300),
                      "lines": (10342, 30962), "branches": (7135, 24934)}


def test_parse_lcov_sets(tmp_path):
    report = tmp_path / "report.json"
    report.write_text("SF:/a.c\nDA:1,5\nDA:2,0\nBRDA:1,0,0,3\nBRDA:1,0,1,0\nBRDA:2,0,0,-\nend_of_record\n")
    lines, branches = sa.parse_lcov_sets(str(report))
    assert lines == {("/a.c", 1)}
    assert branches == {("/a.c", 1, "0", "0")}


def test_trial_identity_from_directory_name(tmp_path):
    ident = sa.trial_identity("aflplusplus_rts_random_cts_default_pcre2_pcre2test_0_trial_3", str(tmp_path))
    assert ident == {"fuzzer": "aflplusplus", "rts": "random", "cts": "default",
                     "benchmark": "pcre2_pcre2test", "copy": 0, "trial": 3}
