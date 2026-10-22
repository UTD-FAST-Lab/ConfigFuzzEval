// Live dashboard of the experiment page: trials with the fuzzer's own statistics, triage, SuperC and logs.
const live = {data: null, timer: null, modal: null, logPath: "", logOffset: -1, sort: "core"};

const fmt = n => n == null ? "–" : Math.round(n).toLocaleString();
function compact(n) {
  if (n == null) return "–";
  const a = Math.abs(n);
  return a >= 1e9 ? (n / 1e9).toFixed(2) + "G" : a >= 1e6 ? (n / 1e6).toFixed(2) + "M" : a >= 1e4 ? (n / 1e3).toFixed(1) + "k" : Math.round(n).toLocaleString();
}
function ago(s) { return s == null ? "–" : s < 1 ? "just now" : duration(s) + " ago"; }

function spark(values, color, label) {
  const v = (values || []).filter(x => Number.isFinite(x));
  if (v.length < 2) return `<div class="sparklabel">${esc(label)}: waiting for data</div>`;
  const min = Math.min(...v), max = Math.max(...v), span = max - min || 1, W = 200, H = 28;
  const pts = v.map((y, i) => `${(W * i / (v.length - 1)).toFixed(1)},${(H - 3 - (H - 6) * (y - min) / span).toFixed(1)}`).join(" ");
  return `<div class="sparklabel">${esc(label)} <b>${compact(v[v.length - 1])}</b></div>
    <svg class="spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none"><polyline points="${pts}" stroke="${color}"/></svg>`;
}

function trialCard(t) {
  const s = t.stats, planned = t.planned, el = t.seconds;
  const pct = planned && el ? Math.min(100, 100 * el / planned) : 0;
  const stage = t.stage === "fuzzing" ? `<span class="stagechip">fuzzing</span>` : `<span class="stagechip cov">coverage / finishing</span>`;
  let body = `<p class="small muted" style="margin:6px 0 0">${t.stage === "fuzzing" ? "No fuzzer statistics yet (the fuzzer is starting, or writes none)." : "The fuzzing time is over; the container exits after the coverage replay."}</p>`;
  if (s) {
    const crash = s.saved_crashes > 0 ? "bad" : "";
    body = `<div class="afl">
      <div><h4>Process timing</h4><dl><dt>run time</dt><dd>${duration(s.run_time)}</dd><dt>last new find</dt><dd>${ago(s.last_find_ago)}</dd><dt>last crash</dt><dd>${s.saved_crashes ? ago(s.last_crash_ago) : "none yet"}</dd></dl></div>
      <div><h4>Overall results</h4><dl><dt>cycles done</dt><dd>${fmt(s.cycles_done)}</dd><dt>corpus</dt><dd>${fmt(s.corpus_count)}${s.corpus_favored != null ? ` <span class="muted">(${fmt(s.corpus_favored)} fav)</span>` : ""}</dd><dt>crashes / hangs</dt><dd class="${crash}">${fmt(s.saved_crashes)} / ${fmt(s.saved_hangs)}</dd></dl></div>
      <div><h4>Speed</h4><dl><dt>execs/sec</dt><dd><b>${fmt(s.execs_per_sec)}</b></dd><dt>total execs</dt><dd>${compact(s.execs_done)}</dd><dt>pending</dt><dd>${fmt(s.pending_total)}${s.pending_favs != null ? ` <span class="muted">(${fmt(s.pending_favs)} fav)</span>` : ""}</dd></dl></div>
      <div><h4>Coverage map</h4><dl><dt>map density</dt><dd>${s.bitmap_cvg != null ? s.bitmap_cvg.toFixed(2) + "%" : "–"}</dd><dt>edges found</dt><dd>${fmt(s.edges_found)}${s.total_edges ? ` <span class="muted">/ ${compact(s.total_edges)}</span>` : ""}</dd><dt>stability</dt><dd>${s.stability != null ? s.stability.toFixed(1) + "%" : "–"}</dd></dl></div></div>
      ${spark(t.series?.execs_per_sec, "var(--cat-1)", "execs/sec")}${spark(t.series?.edges_found?.length ? t.series.edges_found : t.series?.corpus_count, "var(--cat-3)", t.series?.edges_found?.length ? "edges" : "corpus")}`;
  }
  const cfg = t.configs ? `<span class="small muted">configuration ${t.configs} · <code>${esc((t.config_args || []).join(" ").slice(0, 60))}</code></span>` : "";
  return `<div class="tcard" onclick="openTrial('${esc(t.folder)}')">
    <div class="head"><b>${esc(t.arm)}</b><span>${esc(t.bench)}</span>${t.cts !== "default" ? `<span class="meta">cts ${esc(t.cts)}</span>` : ""}<span class="spacer"></span>${stage}</div>
    <div class="meta">trial ${t.trial} · core ${t.core ?? "–"} · ${duration(el)}${planned ? ` of ${duration(planned)}` : ""} ${cfg ? "· " + cfg : ""}</div>
    <div class="progress bar"><span style="width:${pct.toFixed(1)}%"></span></div>${body}</div>`;
}

function renderMatrix(trials) {
  const cols = [...new Set(trials.map(t => t.bench + (t.cts !== "default" ? ` [${t.cts}]` : "")))].sort();
  const arms = [...new Set(trials.map(t => t.arm))].sort();
  const cell = (arm, col) => {
    const ts = trials.filter(t => t.arm === arm && t.bench + (t.cts !== "default" ? ` [${t.cts}]` : "") === col);
    if (!ts.length) return `<td class="cell muted">–</td>`;
    const ok = ts.filter(t => t.status === "success").length, run = ts.filter(t => t.status === "running").length;
    const bad = ts.filter(t => ["failure", "interrupted", "skipped"].includes(t.status)).length, n = ts.length;
    const w = k => (100 * k / n).toFixed(1) + "%";
    return `<td class="cell"><span class="small">${ok}/${n}${run ? ` · <span style="color:var(--accent-ink)">${run} running</span>` : ""}${bad ? ` · <span style="color:var(--bad-ink)">${bad} failed</span>` : ""}</span>
      <div class="stack"><i class="s" style="width:${w(ok)}"></i><i class="r" style="width:${w(run)}"></i><i class="f" style="width:${w(bad)}"></i></div></td>`;
  };
  return `<table class="mx"><thead><tr><th>Arm</th>${cols.map(c => `<th>${esc(c)}</th>`).join("")}</tr></thead><tbody>` +
    arms.map(a => `<tr><td><b>${esc(a)}</b></td>${cols.map(c => cell(a, c)).join("")}</tr>`).join("") + `</tbody></table>`;
}

function phaseDurations(phases, now, running) {
  const out = [];
  phases.forEach((p, i) => {
    const end = phases[i + 1] ? phases[i + 1].time : (running ? now : p.time);
    if (p.phase !== "finished") out.push(`<span class="step ${i === phases.length - 1 && running ? "cur" : ""}">${esc(p.phase)} · ${duration(end - p.time)}</span>`);
  });
  return out.join("");
}

function renderTriage(d) {
  const root = document.getElementById("lv-triage");
  if (d.triage == null) { root.hidden = true; return; }
  root.hidden = false;
  const rows = d.triage.map(t => `<tr><td>${esc(t.triager)}</td><td>${esc(t.run)}</td><td>${esc(t.benchmark)}</td><td>${badge(t.state === "done" ? "success" : t.state === "failed" ? "failure" : "running")}</td>
    <td class="small">${t.trial_logs.map(f => `<a href="#" onclick="openLog('bug-triaging/${esc(t.triager)}/output/${esc(t.run)}_${esc(t.benchmark)}/${esc(f)}');return false">${esc(f.replace(".log", ""))}</a>`).join(" · ") || "<span class='muted'>–</span>"}</td>
    <td class="small">${t.files.filter(f => !f.endsWith(".log") && f !== "pool.json").length} result file(s)</td></tr>`).join("");
  const phaseNow = d.phases.length && d.phases[d.phases.length - 1].phase === "triage" && d.running;
  document.getElementById("lv-triage-body").innerHTML = d.triage.length ?
    `<div class="tw"><table><thead><tr><th>Tool</th><th>Run</th><th>Benchmark</th><th>Status</th><th>Trial logs</th><th>Output</th></tr></thead><tbody>${rows}</tbody></table></div>` :
    `<p class="muted small">${phaseNow ? "Starting." : "Crash triage (" + esc(d.triagers.join(", ")) + ") starts after SuperC, when all trials are done."}</p>`;
}

function renderSuperc(d) {
  const root = document.getElementById("lv-superc");
  if (d.superc == null) { root.hidden = true; return; }
  root.hidden = false;
  const rows = d.superc.map(b => `<tr><td>${esc(b.build)}</td><td>${badge(b.state === "done" ? "success" : b.state === "failed" ? "failure" : "running")}</td>
    <td class="num">${b.files != null ? b.files : "–"}</td><td class="num">${b.seconds != null ? duration(b.seconds) : "–"}</td>
    <td class="small">${b.without_result ? `<span style="color:var(--bad-ink)">${b.without_result} of ${b.files_total} files without a result</span>` : (b.state === "done" ? "all files analysed" : "")}</td></tr>`).join("");
  const now = d.phases.length && d.phases[d.phases.length - 1].phase === "superc" && d.running;
  document.getElementById("lv-superc-body").innerHTML = d.superc.length ?
    `<div class="tw"><table><thead><tr><th>Benchmark build</th><th>Status</th><th class="num">.c files</th><th class="num">Took</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>
     <p class="small muted">The presence-condition tables are in the <a href="#superc" onclick="showTab('superc')">Presence conditions</a> tab once the report is written.</p>` :
    `<p class="muted small">${now ? "Starting." : "SuperC runs once all trials are done."}</p>`;
}

function renderLogs(d) {
  const sel = document.getElementById("lv-logsel"), cur = sel.value;
  const groups = {"experiment": [{path: "", label: "experiment log (setup, trials, aggregation)"}], "builds": [], "trials": [], "triage": [], "SuperC": []};
  for (const l of d.logs) (groups[{build: "builds", triage: "triage", superc: "SuperC"}[l.group]] || groups.builds).push({path: l.path, label: l.path});
  for (const t of d.trials) if (t.log) groups.trials.push({path: t.log, label: `${t.arm} · ${t.bench}${t.cts !== "default" ? " [" + t.cts + "]" : ""} · trial ${t.trial} (${t.status})`});
  sel.innerHTML = Object.entries(groups).filter(([, v]) => v.length).map(([g, v]) =>
    `<optgroup label="${esc(g)}">${v.map(x => `<option value="${esc(x.path)}">${esc(x.label)}</option>`).join("")}</optgroup>`).join("");
  if ([...sel.options].some(o => o.value === cur)) sel.value = cur;
}

function renderLive(d) {
  live.data = d;
  const T = d.trials, run = T.filter(t => t.status === "running"), ok = T.filter(t => t.status === "success");
  const bad = T.filter(t => ["failure", "interrupted", "skipped"].includes(t.status));
  const tot = d.totals;
  document.getElementById("lv-kpis").innerHTML = [
    [run.length, "trials running"], [tot.fuzzing ? fmt(tot.execs_per_sec) : "–", "execs/sec, all running"],
    [tot.fuzzing ? compact(tot.execs_done) : "–", "executions so far (running trials)"],
    [tot.fuzzing ? fmt(tot.saved_crashes) : "–", "crashes found (running)"], [tot.fuzzing ? fmt(tot.saved_hangs) : "–", "hangs found (running)"],
    [`${ok.length} / ${T.length}`, "succeeded"], [bad.length, "failed"]].map(([v, l]) => `<div class="kpi"><div class="v">${v}</div><div class="l">${l}</div></div>`).join("");
  document.getElementById("lv-phases").innerHTML = phaseDurations(d.phases, d.now, d.running);
  document.getElementById("lv-matrix").innerHTML = T.length ? renderMatrix(T) : `<p class="muted small">No trials planned yet.</p>`;
  const sorted = [...run].sort((a, b) => live.sort === "execs" ? (b.stats?.execs_per_sec || 0) - (a.stats?.execs_per_sec || 0) :
    live.sort === "crashes" ? (b.stats?.saved_crashes || 0) - (a.stats?.saved_crashes || 0) : (a.core ?? 0) - (b.core ?? 0));
  document.getElementById("lv-running").innerHTML = sorted.length ? sorted.map(trialCard).join("") :
    `<div class="card empty" style="grid-column:1/-1">${d.running ? "No trial is running at the moment." + (d.phases.length ? " Current phase: " + esc(d.phases[d.phases.length - 1].phase) + "." : "") : "The experiment is not running."}</div>`;
  document.getElementById("lv-running-count").textContent = run.length ? `(${run.length})` : "";
  const row = t => `<tr style="cursor:pointer" onclick="openTrial('${esc(t.folder)}')"><td>${esc(t.arm)}</td><td>${esc(t.bench)}${t.cts !== "default" ? ` <span class="muted">[${esc(t.cts)}]</span>` : ""}</td><td class="num">${t.trial}</td><td>${badge(t.status)}</td>
    <td class="num">${duration(t.seconds)}</td><td class="num">${t.stats ? fmt(t.stats.execs_per_sec) : "–"}</td><td class="num">${t.branches ? t.branches[0].toLocaleString() : "–"}</td>
    <td class="num">${t.stats ? fmt(t.stats.saved_crashes) : "–"}</td></tr>`;
  const head = `<thead><tr><th>Arm</th><th>Benchmark</th><th class="num">Trial</th><th>Status</th><th class="num">Duration</th><th class="num">execs/sec (end)</th><th class="num">Branches</th><th class="num">Crashes</th></tr></thead>`;
  document.getElementById("lv-ok").innerHTML = ok.length ? `<div class="tw"><table>${head}<tbody>${ok.map(row).join("")}</tbody></table></div>` : `<p class="muted small">None yet.</p>`;
  document.getElementById("lv-ok-count").textContent = `(${ok.length})`;
  document.getElementById("lv-bad-count").textContent = `(${bad.length})`;
  document.getElementById("lv-bad").innerHTML = bad.length ? bad.map(t => `<div class="card" style="margin:6px 0"><div class="row"><b>${esc(t.arm)}</b> ${esc(t.bench)}${t.cts !== "default" ? ` [${esc(t.cts)}]` : ""} · trial ${t.trial} ${badge(t.status)}
    <span class="spacer"></span>${t.log ? `<button class="small" onclick="openLog('${esc(t.log)}')">open log</button>` : ""} <button class="small" onclick="openTrial('${esc(t.folder)}')">details</button></div>
    ${t.error ? `<pre class="errtext">${esc(t.error)}</pre>` : ""}</div>`).join("") : `<p class="muted small">No failures.</p>`;
  document.getElementById("lv-bad-wrap").open = bad.length > 0 || document.getElementById("lv-bad-wrap").open;
  renderTriage(d); renderSuperc(d); renderLogs(d);
  if (live.modal) updateModal();
}

// Polls only while the tab is open: each poll reads every running trial's container.
async function loadLive() {
  clearTimeout(live.timer);
  if (!document.getElementById("tab-live").classList.contains("on")) return;
  const d = await api(`/api/experiments/${encodeURIComponent(NAME)}/live`);
  if (d && d.trials) renderLive(d);
  live.timer = setTimeout(loadLive, (d && d.running) ? 4000 : 30000);
}

// ---- Logs viewer ----
async function openLog(path) {
  showTab("live");
  document.getElementById("lv-logsel").value = path;
  if (document.getElementById("lv-logsel").value !== path) {
    const sel = document.getElementById("lv-logsel"); sel.add(new Option(path, path)); sel.value = path;
  }
  document.getElementById("lv-logs-wrap").open = true;
  await loadLiveLog();
  document.getElementById("lv-logs-wrap").scrollIntoView({behavior: "smooth"});
}
async function loadLiveLog() {
  const path = document.getElementById("lv-logsel").value, pre = document.getElementById("lv-log");
  if (!document.getElementById("lv-logs-wrap").open) return;
  let text;
  if (path === "") {
    const r = await api(`/api/experiments/${encodeURIComponent(NAME)}/log?offset=-1`);
    text = r.text;
  } else {
    const r = await fetch(`/experiments/${encodeURIComponent(NAME)}/files/${path.split("/").map(encodeURIComponent).join("/")}`);
    text = r.ok ? await r.text() : "Cannot read this log.";
  }
  const stick = document.getElementById("lv-follow").checked;
  pre.textContent = text || "Empty.";
  if (stick) pre.scrollTop = pre.scrollHeight;
}
setInterval(() => { if (document.getElementById("tab-live").classList.contains("on")) loadLiveLog(); }, 3000);

// ---- Trial detail ----
async function openTrial(folder) {
  live.modal = {folder, data: null, tab: null};
  drawModal();
  const r = await api(`/api/experiments/${encodeURIComponent(NAME)}/trial/${encodeURIComponent(folder)}`);
  live.modal.data = r;
  drawModal();
}
function closeModal() { live.modal = null; document.getElementById("lv-modal").innerHTML = ""; }
async function updateModal() {
  if (!live.modal || !live.modal.data || live.modal.data.source !== "live") return;
  if (live.modal.busy) return;
  live.modal.busy = true;
  const r = await api(`/api/experiments/${encodeURIComponent(NAME)}/trial/${encodeURIComponent(live.modal.folder)}`);
  if (live.modal) { live.modal.data = r; live.modal.busy = false; drawModal(true); }
}
function bigChart(t, ys, color, label) {
  const v = (ys || []), n = Math.min(v.length, t.length);
  if (n < 2) return `<div class="small muted">${esc(label)}: no data yet</div>`;
  const W = 480, H = 120, L = 46, B = 16, xs = t.slice(0, n), x0 = xs[0], x1 = xs[n - 1] || 1;
  const max = Math.max(...v.slice(0, n)) * 1.05 || 1, min = Math.min(0, ...v.slice(0, n));
  const px = (x) => L + (W - L - 6) * (x - x0) / ((x1 - x0) || 1), py = y => 6 + (H - 6 - B) * (1 - (y - min) / ((max - min) || 1));
  const pts = v.slice(0, n).map((y, i) => `${px(xs[i]).toFixed(1)},${py(y).toFixed(1)}`).join(" ");
  return `<div class="small"><b>${esc(label)}</b> <span class="muted">now ${compact(v[n - 1])}, max ${compact(Math.max(...v.slice(0, n)))}</span></div>
    <svg class="bigspark" viewBox="0 0 ${W} ${H}"><line x1="${L}" x2="${W - 6}" y1="${py(0)}" y2="${py(0)}" class="axis" style="stroke:var(--rule)"/>
    <text x="${L - 4}" y="12" text-anchor="end" style="font-size:10px;fill:var(--muted)">${compact(max)}</text><text x="${L - 4}" y="${H - B}" text-anchor="end" style="font-size:10px;fill:var(--muted)">${compact(min)}</text>
    <text x="${L}" y="${H - 3}" style="font-size:10px;fill:var(--muted)">${duration(x0)}</text><text x="${W - 6}" y="${H - 3}" text-anchor="end" style="font-size:10px;fill:var(--muted)">${duration(x1)}</text>
    <polyline points="${pts}" fill="none" stroke="${color}" stroke-width="1.8"/></svg>`;
}
function drawModal(keep) {
  const m = live.modal, root = document.getElementById("lv-modal");
  if (!m) return;
  const t = (live.data?.trials || []).find(x => x.folder === m.folder), d = m.data;
  const title = t ? `${esc(t.arm)} · ${esc(t.bench)}${t.cts !== "default" ? " [" + esc(t.cts) + "]" : ""} · trial ${t.trial}` : esc(m.folder);
  let body = `<p class="muted">Loading…</p>`;
  if (d) {
    const s = d.stats || {}, keys = Object.keys(s), logs = Object.keys(d.logs || {});
    const tab = m.tab && logs.includes(m.tab) ? m.tab : (logs[0] || null); m.tab = tab;
    const prev = root.querySelector("pre.log"), stick = !prev || prev.scrollTop + prev.clientHeight >= prev.scrollHeight - 30;
    body = `<p class="small muted">${d.source === "live" ? "Read from the running container, refreshed every few seconds." : "Statistics the fuzzer left in the trial folder."}${t ? ` ${badge(t.status)}` : ""}</p>` +
      (keys.length ? `<div class="row" style="align-items:flex-start;gap:20px"><div style="flex:1;min-width:300px">${bigChart(d.series.t || [], d.series.execs_per_sec, "var(--cat-1)", "execs/sec")}</div>
        <div style="flex:1;min-width:300px">${bigChart(d.series.t || [], d.series.edges_found?.length ? d.series.edges_found : d.series.corpus_count, "var(--cat-3)", d.series.edges_found?.length ? "edges found" : "corpus size")}</div>
        <div style="flex:1;min-width:300px">${bigChart(d.series.t || [], d.series.saved_crashes, "var(--cat-8)", "saved crashes")}</div></div>
        <h3>fuzzer_stats</h3><div class="statgrid">${keys.map(k => `<div><span>${esc(k)}</span><span>${esc(s[k])}</span></div>`).join("")}</div>` :
        `<div class="card empty">This trial has no fuzzer_stats (the fuzzer may write other files, or has not started).</div>`) +
      ((d.configs || []).length ? `<h3>Runtime configurations (${d.configs.length} started)</h3><div class="tw"><table><thead><tr><th>#</th><th class="num">Time slice</th><th>Options</th></tr></thead><tbody>${d.configs.map(c => `<tr><td>${c.config}</td><td class="num">${duration(c.slice)}</td><td><code>${esc((c.args || []).join(" "))}</code></td></tr>`).join("")}</tbody></table></div>` : "") +
      ((d.crashes || []).length ? `<h3>Crash files</h3><p class="small"><code>${d.crashes.map(esc).join("</code> · <code>")}</code></p>` : "") +
      (logs.length ? `<h3>Logs</h3><div class="row" style="margin-bottom:6px">${logs.map(l => `<button class="small ${l === tab ? "primary" : ""}" onclick="live.modal.tab='${esc(l)}';drawModal()">${esc(l)}</button>`).join("")}</div><pre class="log" id="lv-modal-log">${esc(d.logs[tab])}</pre>` : "");
    root.innerHTML = `<div class="modal" onclick="if(event.target===this)closeModal()"><div class="box"><div class="row"><h3 style="margin:0">${title}</h3><span class="spacer"></span><button onclick="closeModal()">Close</button></div>${body}</div></div>`;
    const pre = root.querySelector("pre.log"); if (pre && stick) pre.scrollTop = pre.scrollHeight;
    return;
  }
  root.innerHTML = `<div class="modal" onclick="if(event.target===this)closeModal()"><div class="box"><div class="row"><h3 style="margin:0">${title}</h3><span class="spacer"></span><button onclick="closeModal()">Close</button></div>${body}</div></div>`;
}
document.addEventListener("keydown", e => { if (e.key === "Escape") closeModal(); });
