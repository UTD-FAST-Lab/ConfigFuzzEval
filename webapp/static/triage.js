// Crash triage tab of the experiment page: every triager's results in one place (webapp/triage_view.py).

const tri = {data: null, triager: null, bench: "", arm: "", shown: 200};

async function loadTriageTab() {
  const r = await api(`/api/experiments/${encodeURIComponent(NAME)}/triage`);
  tri.data = r;
  if (r && r.ok && !r.triagers.includes(tri.triager)) tri.triager = r.triagers.includes("gdb-exploitable") ? "gdb-exploitable" : r.triagers[0];
  renderTriageTab();
}

function triageFile(path, label) {
  return `<a href="/experiments/${encodeURIComponent(NAME)}/files/${path.split("/").map(encodeURIComponent).join("/")}" target="_blank">${esc(label)}</a>`;
}

function renderTriageTab() {
  const root = document.getElementById("triage-body"), r = tri.data;
  if (!r || !r.ok) {
    root.innerHTML = `<div class="card empty">No crash triage results. Crash triage runs after the trials when the experiment asks for it
      (<code>bug_triaging</code> in the experiment file, or <code>--bug-triaging</code>), or from <a href="#analyse" onclick="showTab('analyse')">Post-analysis</a>.</div>`;
    return;
  }
  const t = tri.triager, counts = r.counts[t] || {};
  const tasks = r.tasks.filter(x => x.triager === t);
  const sum = k => tasks.reduce((n, x) => n + (x[k] || 0), 0);
  const distinct = Object.values(counts).reduce((n, b) => n + (b.union || 0), 0);
  const arms = r.arms.filter(a => tasks.some(x => x.arm === a));
  const benches = r.benchmarks.filter(b => tasks.some(x => x.benchmark === b));
  const max = Math.max(1, ...benches.flatMap(b => arms.map(a => (counts[b] || {})[a] || 0)));
  const cell = (b, a) => {
    const n = (counts[b] || {})[a] || 0, on = tri.bench === b && tri.arm === a;
    return `<td class="num" style="cursor:pointer;${n ? `background:color-mix(in srgb, var(--accent) ${Math.round(8 + 32 * n / max)}%, transparent);` : ""}${on ? "outline:2px solid var(--accent);" : ""}"
      onclick="tri.bench=${on ? "''" : `'${esc(b)}'`};tri.arm=${on ? "''" : `'${esc(a)}'`};tri.shown=200;renderTriageTab()" title="List these bugs">${n || `<span class="muted">0</span>`}</td>`;
  };
  const bugs = r.bugs.filter(x => x.triager === t && (!tri.bench || x.benchmark === tri.bench) && (!tri.arm || x.arms[tri.arm]));
  const bugRows = bugs.slice(0, tri.shown).map(x => `<tr>
    <td>${esc(x.benchmark)}</td><td><code>${esc(x.key.slice(0, 16))}</code></td>
    <td class="small">${esc(x.classification || "–")}${x.description ? `<div class="muted">${esc(x.description)}</div>` : ""}</td>
    <td class="small">${x.state ? `<code>${x.state.split("\n").map(esc).join("<br>")}</code>` : `<span class="muted">–</span>`}</td>
    <td class="small">${Object.entries(x.arms).map(([a, n]) => `${esc(a)} <span class="muted">(${n})</span>`).join(", ")}</td>
    <td class="num">${x.crashes}</td>
    <td class="small">${x.command ? `<code>${esc(x.command.slice(0, 160))}</code>` : `<span class="muted">–</span>`}
      ${x.folder && (x.files || []).length ? `<div>${x.files.map(f => triageFile(`${x.folder}/${f}`, f.replace(".txt", ""))).join(" · ")}</div>` : ""}</td></tr>`).join("");
  root.innerHTML = `
    <div class="row" style="margin-bottom:8px">
      <label>Triager <select onchange="tri.triager=this.value;tri.bench='';tri.arm='';renderTriageTab()">${r.triagers.map(x => `<option ${x === t ? "selected" : ""}>${esc(x)}</option>`).join("")}</select></label>
      <span class="small muted">${t === "gdb-exploitable" ? "A bug is a crash state: the signal and the top 3 program frames, as FuzzBench counts bugs."
        : t === "afl-collect" ? "A bug is exploitable's major stack hash (more frames than gdb-exploitable's crash state, so usually more bugs)." : ""}</span>
    </div>
    <div class="kpis">
      <div class="kpi"><div class="v">${distinct}</div><div class="l">distinct bugs (per benchmark, all arms)</div></div>
      <div class="kpi"><div class="v">${sum("crashes")}</div><div class="l">crashes replayed</div></div>
      <div class="kpi"><div class="v">${sum("reproduced")}</div><div class="l">crashed again</div></div>
      <div class="kpi"><div class="v">${arms.length}</div><div class="l">arms</div></div>
      <div class="kpi"><div class="v">${tasks.length}</div><div class="l">benchmark copies triaged</div></div>
    </div>
    <p class="small muted">Every crash is replayed on its benchmark copy's coverage build with the command line it was found with
      (its runtime configuration, or the arguments a config-aware fuzzer saved). Crashes that crash again are grouped into bugs,
      pooled over an arm's trials, with the copies of a compile-time strategy combined, as the statistics report's Found bugs.</p>
    <h3>Found bugs <span class="small muted">distinct bugs per benchmark and arm; click a number to list them</span></h3>
    <div class="tw"><table><thead><tr><th>Benchmark</th>${arms.map(a => `<th class="num">${esc(a)}</th>`).join("")}<th class="num">Union</th></tr></thead>
      <tbody>${benches.map(b => `<tr><td>${esc(b)}</td>${arms.map(a => cell(b, a)).join("")}<td class="num"><b>${(counts[b] || {}).union || 0}</b></td></tr>`).join("")}</tbody></table></div>
    <h3>Bugs${tri.bench ? ` <span class="small muted">${esc(tri.bench)}${tri.arm ? " · " + esc(tri.arm) : ""} · <a href="#" onclick="tri.bench='';tri.arm='';renderTriageTab();return false">show all</a></span>` : ""}</h3>
    ${bugs.length ? `<div class="tw"><table><thead><tr><th>Benchmark</th><th>Bug</th><th>Classification</th><th>Crash state</th><th>Found by (crashes)</th><th class="num">Crashes</th><th>Replayed with</th></tr></thead>
      <tbody>${bugRows}</tbody></table></div>
      ${bugs.length > tri.shown ? `<p class="small"><a href="#" onclick="tri.shown+=200;renderTriageTab();return false">Show more</a> <span class="muted">(${tri.shown} of ${bugs.length})</span></p>` : ""}`
      : `<div class="card empty">No crash crashed again${tri.bench ? " here" : ""}: no bugs.</div>`}
    <details style="margin-top:12px"><summary><b>Every triaged benchmark copy</b> <span class="muted">(${tasks.length}): crashes, bugs and the triage logs</span></summary>
      <div class="tw"><table><thead><tr><th>Arm</th><th>Benchmark copy</th><th class="num">Trials</th><th class="num">Crashes</th><th class="num">Crashed again</th><th class="num">Bugs</th><th>Logs</th></tr></thead>
      <tbody>${tasks.map(x => `<tr><td>${esc(x.arm)}</td><td>${esc(x.copy)}</td><td class="num">${x.trials.length}</td>
        <td class="num">${x.crashes ?? "–"}</td><td class="num">${x.reproduced ?? "–"}</td><td class="num">${x.bugs}</td>
        <td class="small">${x.logs.map(l => triageFile(l, l.split("/").pop().replace(".log", ""))).join(" · ") || "–"}</td></tr>`).join("")}</tbody></table></div>
    </details>`;
}
