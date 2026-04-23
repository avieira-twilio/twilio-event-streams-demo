/**
 * Twilio Event Streams Demo Dashboard
 * Fetches data from the Flask JSON API and renders Chart.js charts + data tables.
 */

// ---------------------------------------------------------------------------
// Palette — one colour per subaccount (cycles if more than 8)
// ---------------------------------------------------------------------------
const PALETTE = [
  "#f22f46", "#1a73e8", "#0d7a4a", "#f5a623",
  "#9b59b6", "#1abc9c", "#e67e22", "#2c3e50",
];
const colorFor = (() => {
  const cache = {};
  let idx = 0;
  return (sid) => {
    if (!cache[sid]) cache[sid] = PALETTE[idx++ % PALETTE.length];
    return cache[sid];
  };
})();

// ---------------------------------------------------------------------------
// Filter state
// ---------------------------------------------------------------------------
let filters = { account_sid: "", from: "", to: "", status: "" };
let callsPage = 1;
let confsPage = 1;
let recsPage = 1;

// ---------------------------------------------------------------------------
// Bootstrap
// ---------------------------------------------------------------------------
document.addEventListener("DOMContentLoaded", async () => {
  await populateSubaccounts();
  wireFilters();
  wireTabs();
  await refreshAll();
});

async function populateSubaccounts() {
  const res = await fetch("/api/subaccounts");
  if (!res.ok) return;
  const sids = await res.json();
  const sel = document.getElementById("filter-account");
  sids.forEach((sid) => {
    const opt = document.createElement("option");
    opt.value = sid;
    opt.textContent = sid;
    sel.appendChild(opt);
  });
}

function wireFilters() {
  document.getElementById("apply-filters").addEventListener("click", () => {
    filters.account_sid = document.getElementById("filter-account").value;
    filters.from = document.getElementById("filter-from").value;
    filters.to = document.getElementById("filter-to").value;
    filters.status = document.getElementById("filter-status").value;
    callsPage = 1;
    confsPage = 1;
    recsPage = 1;
    refreshAll();
  });

  document.getElementById("reset-filters").addEventListener("click", () => {
    filters = { account_sid: "", from: "", to: "", status: "" };
    callsPage = 1;
    confsPage = 1;
    recsPage = 1;
    document.getElementById("filter-account").value = "";
    document.getElementById("filter-from").value = "";
    document.getElementById("filter-to").value = "";
    document.getElementById("filter-status").value = "";
    refreshAll();
  });
}

function wireTabs() {
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
      btn.classList.add("active");
      document.getElementById("tab-" + btn.dataset.tab).classList.add("active");
    });
  });
}

// ---------------------------------------------------------------------------
// Fetch helpers
// ---------------------------------------------------------------------------
function buildQS(extra = {}) {
  const params = { ...filters, ...extra };
  return new URLSearchParams(
    Object.fromEntries(Object.entries(params).filter(([, v]) => v !== ""))
  ).toString();
}

async function apiFetch(path, extra = {}) {
  const qs = buildQS(extra);
  const res = await fetch(`${path}?${qs}`);
  if (!res.ok) throw new Error(`${path} ${res.status}`);
  return res.json();
}

async function refreshAll() {
  setLoading(true);
  try {
    await Promise.all([
      renderVolumeChart(),
      renderDurationChart(),
      renderErrorChart(),
      renderStatusChart(),
      renderCallsTable(),
      renderConferencesTable(),
      renderRecordingsTable(),
    ]);
  } finally {
    setLoading(false);
  }
}

function setLoading(on) {
  document.getElementById("loading-overlay").classList.toggle("visible", on);
}

// ---------------------------------------------------------------------------
// Charts
// ---------------------------------------------------------------------------
const chartInstances = {};

function upsertChart(id, config) {
  if (chartInstances[id]) chartInstances[id].destroy();
  const ctx = document.getElementById(id).getContext("2d");
  chartInstances[id] = new Chart(ctx, config);
}

async function renderVolumeChart() {
  const data = await apiFetch("/api/charts/call-volume");

  // Group by account_sid for multi-line
  const dates = [...new Set(data.map((d) => d.date))].sort();
  const bySid = {};
  data.forEach(({ date, account_sid, count }) => {
    if (!bySid[account_sid]) bySid[account_sid] = {};
    bySid[account_sid][date] = count;
  });

  const datasets = Object.entries(bySid).map(([sid, byDate]) => ({
    label: sid,
    data: dates.map((d) => byDate[d] || 0),
    borderColor: colorFor(sid),
    backgroundColor: colorFor(sid) + "22",
    tension: 0.3,
    fill: false,
  }));

  upsertChart("chart-volume", {
    type: "line",
    data: { labels: dates, datasets },
    options: { responsive: true, plugins: { legend: { position: "bottom" } } },
  });
}

async function renderDurationChart() {
  const data = await apiFetch("/api/charts/call-duration");
  upsertChart("chart-duration", {
    type: "bar",
    data: {
      labels: data.map((d) => d.account_sid),
      datasets: [{
        label: "Avg duration (s)",
        data: data.map((d) => d.avg_duration),
        backgroundColor: data.map((d) => colorFor(d.account_sid)),
      }],
    },
    options: {
      responsive: true,
      plugins: { legend: { display: false } },
      scales: { y: { beginAtZero: true } },
    },
  });
}

async function renderErrorChart() {
  const data = await apiFetch("/api/charts/error-rate");
  const dates = [...new Set(data.map((d) => d.date))].sort();
  const bySid = {};
  data.forEach(({ date, account_sid, errors, total }) => {
    if (!bySid[account_sid]) bySid[account_sid] = {};
    bySid[account_sid][date] = total > 0 ? ((errors / total) * 100).toFixed(1) : 0;
  });

  const datasets = Object.entries(bySid).map(([sid, byDate]) => ({
    label: sid,
    data: dates.map((d) => byDate[d] || 0),
    borderColor: colorFor(sid),
    backgroundColor: colorFor(sid) + "22",
    tension: 0.3,
    fill: false,
  }));

  upsertChart("chart-errors", {
    type: "line",
    data: { labels: dates, datasets },
    options: {
      responsive: true,
      plugins: { legend: { position: "bottom" } },
      scales: { y: { beginAtZero: true, title: { display: true, text: "Error %" } } },
    },
  });
}

async function renderStatusChart() {
  const data = await apiFetch("/api/charts/call-status");

  // Aggregate across all subaccounts (or the selected one)
  const totals = {};
  data.forEach(({ status, count }) => {
    totals[status] = (totals[status] || 0) + count;
  });

  const labels = Object.keys(totals);
  const STATUS_COLORS = {
    completed: "#0d7a4a", failed: "#c0392b", busy: "#e67e22",
    "no-answer": "#95a5a6", canceled: "#bdc3c7", "in-progress": "#1a73e8",
  };

  upsertChart("chart-status", {
    type: "doughnut",
    data: {
      labels,
      datasets: [{
        data: labels.map((l) => totals[l]),
        backgroundColor: labels.map((l) => STATUS_COLORS[l] || "#aaa"),
      }],
    },
    options: { responsive: true, plugins: { legend: { position: "right" } } },
  });
}

// ---------------------------------------------------------------------------
// Tables
// ---------------------------------------------------------------------------
function statusBadge(status) {
  const cls = {
    completed: "badge-completed", failed: "badge-failed",
    busy: "badge-busy", "no-answer": "badge-no-answer",
    "in-progress": "badge-in-progress",
  }[status] || "badge-default";
  return `<span class="badge ${cls}">${status || "—"}</span>`;
}

function fmtDt(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString();
}

async function renderCallsTable() {
  const data = await apiFetch("/api/calls", { page: callsPage });
  const tbody = document.getElementById("calls-tbody");
  if (!data.items.length) {
    tbody.innerHTML = `<tr><td colspan="8" style="text-align:center;color:#aaa;padding:2rem">No records found.</td></tr>`;
    document.getElementById("calls-pagination").innerHTML = "";
    return;
  }
  tbody.innerHTML = data.items.map((r) => `
    <tr>
      <td style="font-family:monospace;font-size:0.78rem">${r.call_sid}</td>
      <td style="font-family:monospace;font-size:0.78rem">${r.account_sid}</td>
      <td>${r.direction || "—"}</td>
      <td>${r.from_number || "—"}</td>
      <td>${r.to_number || "—"}</td>
      <td>${statusBadge(r.status)}</td>
      <td>${r.duration_seconds ?? "—"}</td>
      <td>${fmtDt(r.started_at)}</td>
    </tr>
  `).join("");
  renderPagination("calls-pagination", data.page, data.pages, (p) => { callsPage = p; renderCallsTable(); });
}

async function renderConferencesTable() {
  const data = await apiFetch("/api/conferences", { page: confsPage });
  const tbody = document.getElementById("conferences-tbody");
  if (!data.items.length) {
    tbody.innerHTML = `<tr><td colspan="7" style="text-align:center;color:#aaa;padding:2rem">No records found.</td></tr>`;
    document.getElementById("conferences-pagination").innerHTML = "";
    return;
  }
  tbody.innerHTML = data.items.map((r) => `
    <tr>
      <td style="font-family:monospace;font-size:0.78rem">${r.conference_sid}</td>
      <td style="font-family:monospace;font-size:0.78rem">${r.account_sid}</td>
      <td>${r.friendly_name || "—"}</td>
      <td>${statusBadge(r.status)}</td>
      <td>${r.participant_count ?? "—"}</td>
      <td>${r.duration_seconds ?? "—"}</td>
      <td>${fmtDt(r.started_at)}</td>
    </tr>
  `).join("");
  renderPagination("conferences-pagination", data.page, data.pages, (p) => { confsPage = p; renderConferencesTable(); });
}

async function renderRecordingsTable() {
  const data = await apiFetch("/api/recordings", { page: recsPage });
  const tbody = document.getElementById("recordings-tbody");
  if (!data.items.length) {
    tbody.innerHTML = `<tr><td colspan="9" style="text-align:center;color:#aaa;padding:2rem">No recordings found.</td></tr>`;
    document.getElementById("recordings-pagination").innerHTML = "";
    return;
  }
  tbody.innerHTML = data.items.map((r) => {
    // Always use Play button — replaces itself with a compact audio player on click
    const playBtn = `<button class="btn btn-secondary rec-play-btn"
        style="font-size:0.75rem;padding:3px 10px"
        onclick="playRecording(this,'${r.recording_sid}','${r.source}')">&#9654; Play</button>`;

    const dlBtn = r.source === "s3"
      ? `<button class="btn btn-secondary" style="font-size:0.75rem;padding:3px 8px"
           onclick="downloadS3Recording('${r.recording_sid}','${r.recording_sid}.mp3')">&#8595;</button>`
      : `<a href="/api/recordings/proxy/${r.recording_sid}" download="${r.recording_sid}.mp3"
           class="btn btn-secondary" style="font-size:0.75rem;padding:3px 8px">&#8595;</a>`;

    const sourceBadge = r.source === "s3"
      ? `<span class="badge" style="background:#1a73e8;color:#fff">S3</span>`
      : `<span class="badge badge-default">Twilio</span>`;

    const sid  = (s) => `<span title="${s}" style="font-family:monospace;font-size:0.78rem;
        display:inline-block;max-width:160px;overflow:hidden;text-overflow:ellipsis;
        white-space:nowrap;vertical-align:bottom">${s}</span>`;

    return `
      <tr>
        <td>${sid(r.recording_sid)}</td>
        <td>${sid(r.account_sid)}</td>
        <td>${sid(r.call_sid || "—")}</td>
        <td>${statusBadge(r.status)}</td>
        <td>${r.duration_seconds ?? "—"}</td>
        <td>${r.channels === 2 ? "Dual" : "Mono"}</td>
        <td>${sourceBadge}</td>
        <td style="white-space:nowrap">${fmtDt(r.recorded_at)}</td>
        <td style="white-space:nowrap">${playBtn} ${dlBtn}</td>
      </tr>
    `;
  }).join("");
  renderPagination("recordings-pagination", data.page, data.pages, (p) => { recsPage = p; renderRecordingsTable(); });
}

// Unified play handler — fetches presigned URL for S3, uses proxy for Twilio
async function playRecording(btn, recordingSid, source) {
  btn.disabled = true;
  btn.textContent = "Loading…";
  try {
    let audioUrl;
    if (source === "s3") {
      const res = await fetch(`/api/recordings/presign/${recordingSid}`);
      if (!res.ok) throw new Error("presign failed");
      const { url } = await res.json();
      audioUrl = url;
    } else {
      audioUrl = `/api/recordings/proxy/${recordingSid}`;
    }
    const audio = document.createElement("audio");
    audio.controls = true;
    audio.style.cssText = "height:28px;max-width:160px;vertical-align:middle";
    audio.src = audioUrl;
    btn.replaceWith(audio);
    audio.play();
  } catch {
    btn.disabled = false;
    btn.textContent = "▶ Play";
  }
}

async function downloadS3Recording(recordingSid, filename) {
  try {
    const res = await fetch(`/api/recordings/presign/${recordingSid}`);
    if (!res.ok) throw new Error("presign failed");
    const { url } = await res.json();
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
  } catch {
    alert("Could not generate download link. Check S3 configuration.");
  }
}

function renderPagination(containerId, current, total, onPageClick) {
  const el = document.getElementById(containerId);
  if (total <= 1) { el.innerHTML = ""; return; }
  const pages = [];
  for (let p = Math.max(1, current - 2); p <= Math.min(total, current + 2); p++) pages.push(p);
  el.innerHTML = [
    current > 1 ? `<button class="btn btn-secondary" data-page="${current - 1}">&laquo;</button>` : "",
    ...pages.map((p) =>
      `<button class="btn ${p === current ? "btn-primary" : "btn-secondary"}" data-page="${p}">${p}</button>`
    ),
    current < total ? `<button class="btn btn-secondary" data-page="${current + 1}">&raquo;</button>` : "",
    `<span style="color:#888">Page ${current} of ${total}</span>`,
  ].join("");
  el.querySelectorAll("[data-page]").forEach((btn) => {
    btn.addEventListener("click", () => onPageClick(parseInt(btn.dataset.page)));
  });
}
