# Live demo

[ConfigFuzzEval](../README.md) › [Documentation](README.md) › Live demo

**https://configfuzzeval.vercel.app/** is a copy of the [web app](web-app.md) that runs in the browser alone, to try
ConfigFuzzEval without installing anything. No server is behind it, so nothing runs: every page, tab, filter and
report works, but queueing an experiment or a post-analysis shows a notice instead. To run experiments, install
ConfigFuzzEval on a fuzzing machine (see [Installation](README.md#installation)).

## What is in it

| Address | Experiment | Data |
|---|---|---|
| [`/experiments/1`](https://configfuzzeval.vercel.app/experiments/1) | `aflpp_vafuzz_rts-all_cts-default_24h`: AFL++ under every [runtime strategy](../README.md#runtime-strategies), and VAFuzz, on six benchmarks with the default build | mock |
| [`/experiments/2`](https://configfuzzeval.vercel.app/experiments/2) | `aflpp_vafuzz_cts-all_rts-default_24h`: AFL++ and VAFuzz under every [compile-time strategy](../README.md#compile-time-strategies), with the default runtime strategy | mock |
| [`/experiments/live_demo`](https://configfuzzeval.vercel.app/experiments/live_demo) | a real 14-trial run with [SuperC](superc.md), [crash triage](crash-triage.md) and the [statistics report](statistics-report.md), replayed as if it were running now, about 5× faster than it ran | real |

**Mock data.** Experiments 1 and 2 were not run. Their numbers are made up, following the levels of real 24-hour
runs, with noise per trial. Their statistics reports, [combined coverage reports](coverage-reports.md#combined-coverage-reports)
and SuperC reports were computed with the framework's own scripts on synthetic coverage matching those numbers. The
site says so on the home page and on each of their pages. Use them to see what the reports look like, not for
results.

## Addresses

Every page and tab has its own address, so a link opens exactly that view:

| Page | Address |
|---|---|
| [Experiments](web-app.md#experiments-page) | [`/`](https://configfuzzeval.vercel.app/) |
| [New experiment](web-app.md#new-experiment) | [`/new`](https://configfuzzeval.vercel.app/new) |
| [Documentation](web-app.md#documentation-page) | [`/docs`](https://configfuzzeval.vercel.app/docs) |
| `configure.yaml` editor (demo only) | [`/configure`](https://configfuzzeval.vercel.app/configure) |
| [An experiment](web-app.md#an-experiments-page) | `/experiments/<id>`, for example [`/experiments/1`](https://configfuzzeval.vercel.app/experiments/1) |
| One of its tabs | `/experiments/<id>/<tab>`, with `<tab>` one of `live`, `trials`, `log`, `results`, `superc`, `overtime`, `analyse`, `file`; for example [`/experiments/2/superc`](https://configfuzzeval.vercel.app/experiments/2/superc) |

The ids `1` and `2` are short names for the two mock experiments; an experiment without one uses its name
(`/experiments/live_demo/results`).

## How it differs from the web app

- **Nothing runs.** **Queue** on the New experiment page, the post-analyses and **Stop experiment** show a notice.
  The New experiment page still checks the experiment and shows its preview and time estimate, computed in the
  browser.
- **Demo-only extras**, which the web app in this repository does not have:
  - a **`configure.yaml` editor**, to change the machine configuration (cores, default trials and time) and see how
    the estimates change; it is saved in your browser only;
  - the **replay** of `live_demo`.
- **The rest is the same**: the pages, tabs and reports are the web app's, as described with screenshots in
  [The web app](web-app.md).

## See also

- [The web app](web-app.md): every page and tab, with screenshots taken from this demo.
- [Running an experiment](README.md#running-an-experiment): the four ways to run one yourself.
