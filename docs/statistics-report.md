# Statistics report

[ConfigFuzzEval](../README.md) › [Documentation](README.md) › Statistics report

## What it contains

At the end of every experiment, `common/statistical_analysis.py` compares the experiment's arms and writes `<report_filestore>/EXP_NAME/statistics/index.html`, with CSV tables (`trials.csv`, `benchmark_ranking.csv`, `overall_ranking.csv`, `pairwise_tests.csv`) next to it. An [arm](../README.md#experiments-runs-trials-and-arms) is a fuzzer under one runtime strategy, written `fuzzer[strategy]` (`{cts:...}` is added for a non-default compile-time strategy). The report gives a ranking per benchmark and an overall ranking, and has these parts:

- **Per benchmark:** median, minimum, maximum, IQR and CV of the final coverage, plotted as box plots. Two-sided Mann-Whitney U with Vargha-Delaney A12 against the default runtime strategy and the baseline fuzzer. Kruskal-Wallis with Dunn's test. Pairwise p-value and A12 heatmaps. The one-sided better-than matrix with wins. Unique, pairwise-unique and Jaccard coverage, and an UpSet plot.
- **Across benchmarks:** average rank, average normalized score, first places, unique-coverage rankings, Friedman with a Nemenyi critical-difference diagram, and correlations between rankings. Each is given for all arms, for each fuzzer's runtime strategies, and for the fuzzers under their default strategy.
- **Other tables:** relative coverage, benchmark properties, found bugs (from [crash triage](crash-triage.md), per arm), and minimum achievable p-values with low-sample flags.

Every pairwise table uses Holm correction. Coverage comes from each trial's `coverage/report.txt`, and covered sets from `coverage/report.json`. To run the report on a finished experiment:

```bash
python3 common/post_analysis.py --state /path/to/experiment-data/EXP_NAME/experiment_state.pkl --stats
```

Options:

- `--metric lines|branches|regions|functions`: the metric to rank by. The default is `branches`.
- `--baseline FUZZER`: the fuzzer the other fuzzers are compared against. The default is `aflplusplus`.
- `--compare-to /path/to/other/experiment`: adds a reproducibility section, with the rank correlation and changes in significance between the two experiments. Use it for a repeated run, or for a run with one setting changed.
- `--per-config-coverage`: first writes one coverage report per runtime configuration (with Docker), so that the report can compare each trial's union over configurations with its best single configuration.
- `--no-stats-html`: skips the combined coverage reports, which are otherwise always written (see [Coverage reports](coverage-reports.md#combined-coverage-reports)).


The report links each arm's combined coverage reports, the union and the mean of its trials: see [Coverage reports](coverage-reports.md#combined-coverage-reports).

### Limits of the analyses

Some analyses are computed, but do not mean what their names suggest for typical ConfigFuzzEval experiments. The report warns at the top when items 1 and 2 apply. The numbers below are from a test run with 5 arms (aflplusplus with 4 runtime strategies, and zigzagfuzz), 2 benchmarks and 5 trials of 300 s.

1. **Full pairwise heatmaps need many trials.** With n trials per arm, an exact two-sided Mann-Whitney U test cannot go below 2 / C(2n, n): 0.1 for 3 trials and 0.008 for 5. Holm multiplies the smallest p-value by the number of pairs. With 5 trials and 5 arms (10 pairs), no cell of the two-sided heatmap can reach p < 0.05, whatever the data.
   - **What has power:** the **Against the default** table only compares each runtime strategy with its fuzzer's default, and each fuzzer with the baseline, so Holm covers a few tests. There, 5 trials can show a significant difference.
   - **Recommendation:** use that table as the main test, and plan 10 or more trials before reading the full heatmaps.
   - **The better-than matrix:** it can show wins where the two-sided heatmap cannot, because a one-sided test has half the p-value floor.
   - **Dunn's test:** it has the same problem as the heatmaps.
2. **The Friedman test and the Nemenyi critical-difference diagram need many benchmarks.** The critical difference shrinks with the square root of the number of benchmarks. With 2 benchmarks and 5 arms it is 4.31 ranks, wider than the whole rank range, so the diagram joins every arm in one group.
   - **What is still valid:** the average ranks, normalized scores and first places.
   - **What needs more benchmarks:** the significance of the ranking. Expect it to separate arms only with most of the 12 benchmarks.
3. **Correlations between rankings are computed over the arms**, usually 3–5 values. Their p-values tell nothing at that size, and the report gives exact permutation p-values to make that visible. Read ρ and τ as descriptions, not tests.
4. **Unique coverage rewards variance.** It is computed on the union of all of an arm's trials. An arm whose trials differ a lot (as multi-configuration runtime strategies do) collects a large union even when its typical trial is weak. On objdump, `random` had the lowest median (1,984 branches) and close to the largest union (4,632). Unique coverage is also only comparable between arms with the same number of trials (see the low-sample flag).
5. **"Union against best single configuration" is not a comparison with a single configuration.** A runtime strategy fuzzes its configurations one after another, each starting from the previous corpus. A configuration's report only replays the inputs first found under it, with its own options. Its "best single" value is therefore that configuration's share of the trial, not what it would reach running alone for the whole time. To compare with single configurations, run them as separate experiments. Also, with 300 s and `min_config_time` 60 s, a trial fuzzes at most 5 configurations, and those without new inputs are left out.
6. **Found bugs are a secondary metric.** Crashes are sparse, and one bug reached through different stacks can count more than once (see [Crash triage](crash-triage.md)).
7. **The benchmark properties table has no input format.** Nothing in `benchmarks/<name>/` records it, so the column is left out.
8. **Reproducibility and sensitivity need a second experiment.** `--compare-to` gives the rank correlation and the significance changes against another experiment. The other experiment can be a repeat with the same file (reproducibility), or a run with one setting changed, such as seeds, dictionary or a longer time (sensitivity). Both experiments need the same arms and benchmarks.
9. **Host settings affect every number.** Without `run_as_sudo.sh` (see [Installation](README.md#installation)) (CPU governor `powersave`, `core_pattern` not `core`), trials vary more, which weakens every test above. The [web app](web-app.md)'s Experiments page shows both settings.

`python3 common/statistical_analysis.py EXPERIMENT_PATH -o OUT_DIR [--metric ...] [--no-html]` does the same without an experiment state (`--no-html` as `--no-stats-html`).

## See also

- [Coverage reports](coverage-reports.md): the combined union and mean reports, and redoing the coverage of an experiment.
- [Results tab](web-app.md#results) of the web app, which shows this report.
