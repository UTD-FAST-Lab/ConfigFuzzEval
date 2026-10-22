// Shared helpers for the ConfigFuzzEval web app pages.
async function api(url, body) {
  const opts = body === undefined ? {} : {
    method: "POST", headers: {"Content-Type": "application/json", "X-FBPP": "1"}, body: JSON.stringify(body),
  };
  const r = await fetch(url, opts);
  let data = null;
  try { data = await r.json(); } catch (e) { data = {ok: false, error: `HTTP ${r.status}`}; }
  if (!r.ok && data && data.ok === undefined) data.ok = false;
  return data;
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
}

function badge(status) { return `<span class="badge ${esc(status)}">${esc(status)}</span>`; }

function duration(s) {
  if (s == null) return "–";
  s = Math.max(0, Math.round(s));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  return h ? `${h}h ${String(m).padStart(2, "0")}m` : m ? `${m}m ${String(sec).padStart(2, "0")}s` : `${sec}s`;
}

async function cancelJob(id, button) {
  if (!confirm("Stop this job? Its processes and trial containers are killed; finished trials are kept.")) return;
  if (button) button.disabled = true;
  const r = await api(`/api/jobs/${id}/cancel`, {});
  if (!r.ok) alert("The job could not be cancelled (it may have finished already).");
  setTimeout(() => location.reload(), 800);
}
