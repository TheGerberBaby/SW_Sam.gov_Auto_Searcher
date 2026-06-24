"""Single-page operator dashboard UI.

The dashboard backend lives in scripts/dashboard.py. This module only returns a
self-contained HTML document that talks to the existing JSON endpoints.
"""

from __future__ import annotations

import json
from pathlib import Path


def render_dashboard_html(project_root: Path) -> str:
    return _HTML_DOC.replace("__PROJECT_ROOT_JSON__", json.dumps(str(project_root)))


_HTML_DOC = r"""<!doctype html>
<html lang="en" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#101820">
<link rel="manifest" href="/manifest.webmanifest">
<link rel="icon" href="/icon.svg" type="image/svg+xml">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<title>Stormwind Contracting Bots</title>
<style>
:root{
  --bg:#101820;
  --panel:#17232d;
  --panel-2:#1f2d37;
  --line:#31414d;
  --text:#f2f6f8;
  --muted:#a8b6bf;
  --soft:#d7e1e6;
  --green:#44c78f;
  --blue:#68a8e8;
  --gold:#e7b84e;
  --red:#e36d70;
  --ink:#101820;
}
html[data-theme="light"]{
  --bg:#f4f6f8;
  --panel:#ffffff;
  --panel-2:#eef2f4;
  --line:#d6dee3;
  --text:#14202a;
  --muted:#60717c;
  --soft:#263641;
  --ink:#ffffff;
}
*{box-sizing:border-box}
html{background:var(--bg);color:var(--text)}
body{
  margin:0;
  min-height:100vh;
  font-family:Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif;
  background:var(--bg);
  color:var(--text);
  letter-spacing:0;
  -webkit-font-smoothing:antialiased;
}
button,input,select,textarea{font:inherit;letter-spacing:0}
a{color:var(--blue);text-decoration:none}
a:hover{text-decoration:underline}
.shell{max-width:1440px;margin:0 auto;padding:18px}
.topbar{
  position:sticky;
  top:0;
  z-index:5;
  margin:-18px -18px 18px;
  padding:14px 18px;
  background:color-mix(in srgb,var(--bg) 88%,transparent);
  backdrop-filter:blur(14px);
  border-bottom:1px solid var(--line);
}
.toprow{display:flex;align-items:center;gap:14px}
.brand{display:flex;align-items:center;gap:10px;min-width:0}
.mark{
  width:34px;height:34px;border-radius:8px;background:var(--green);color:#09130f;
  display:grid;place-items:center;font-weight:900;flex:0 0 auto;
}
.brand h1{margin:0;font-size:20px;line-height:1.1;white-space:nowrap}
.brand p{margin:2px 0 0;color:var(--muted);font-size:13px}
.spacer{flex:1}
.statusline{display:flex;align-items:center;gap:8px;flex-wrap:wrap;justify-content:flex-end}
.chip{
  display:inline-flex;align-items:center;gap:6px;min-height:28px;padding:4px 9px;
  border:1px solid var(--line);border-radius:8px;background:var(--panel-2);
  color:var(--muted);font-size:12px;font-weight:700;white-space:nowrap;
}
.dot{width:8px;height:8px;border-radius:50%;background:var(--green)}
.buttonbar{display:flex;gap:8px;flex-wrap:wrap;margin-top:14px}
button,.btn{
  min-height:38px;border-radius:8px;border:1px solid var(--line);background:var(--panel-2);
  color:var(--text);padding:7px 11px;font-weight:750;cursor:pointer;text-decoration:none;
  display:inline-flex;align-items:center;justify-content:center;gap:6px;
}
button:hover,.btn:hover{border-color:var(--blue);text-decoration:none}
button.primary,.btn.primary{background:var(--green);border-color:var(--green);color:#06120d}
button.danger{color:#ffd1d1;border-color:color-mix(in srgb,var(--red) 55%,var(--line))}
button.small,.btn.small{min-height:30px;padding:4px 8px;font-size:12px}
input,select,textarea{
  width:100%;
  min-height:38px;
  border-radius:8px;
  border:1px solid var(--line);
  background:var(--panel-2);
  color:var(--text);
  padding:7px 10px;
  outline:none;
}
textarea{min-height:92px;resize:vertical}
input:focus,select:focus,textarea:focus{border-color:var(--blue);box-shadow:0 0 0 3px color-mix(in srgb,var(--blue) 24%,transparent)}
label{display:flex;flex-direction:column;gap:5px;color:var(--muted);font-size:12px;font-weight:800;text-transform:uppercase}
.contextbar{
  margin-top:14px;
  border:1px solid var(--line);
  border-radius:8px;
  background:var(--panel-2);
  padding:10px 12px;
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:12px;
}
.context-title{font-size:12px;font-weight:850;color:var(--muted);text-transform:uppercase}
.context-value{margin-top:3px;font-size:14px;font-weight:800;overflow-wrap:anywhere}
.context-note{font-size:12px;color:var(--muted);max-width:420px;line-height:1.35}
.grid{
  display:grid;
  grid-template-columns:minmax(320px,1.3fr) minmax(300px,.95fr) minmax(280px,.85fr);
  gap:14px;
  align-items:start;
}
.section{
  background:var(--panel);
  border:1px solid var(--line);
  border-radius:8px;
  padding:14px;
  min-width:0;
}
.section h2{margin:0;font-size:15px;text-transform:uppercase;color:var(--soft);letter-spacing:0}
.section-head{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:12px}
.section-actions{display:flex;gap:7px;flex-wrap:wrap;justify-content:flex-end}
.stats{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin:0 0 14px}
.stat{
  border:1px solid var(--line);
  border-radius:8px;
  background:var(--panel);
  padding:12px;
  min-width:0;
}
.stat-button{display:block;text-align:left;width:100%;color:var(--text)}
.stat-button:hover{border-color:var(--green)}
.stat b{display:block;font-size:24px;line-height:1}
.stat span{display:block;margin-top:5px;color:var(--muted);font-size:12px;font-weight:700}
.results,.stack{display:flex;flex-direction:column;gap:9px}
.scan-review{grid-column:1 / span 2}
.scan-review-grid{display:grid;grid-template-columns:minmax(300px,.8fr) minmax(360px,1.2fr);gap:12px;align-items:start}
.scan-history-pane,.scan-results-pane{min-width:0}
.scan-results-pane{
  border-left:1px solid var(--line);
  padding-left:12px;
  position:sticky;
  top:12px;
  max-height:calc(100vh - 24px);
  overflow:auto;
}
.card{
  border:1px solid var(--line);
  border-radius:8px;
  background:var(--panel-2);
  padding:12px;
  min-width:0;
}
.card.selected{border-color:var(--green);box-shadow:0 0 0 2px color-mix(in srgb,var(--green) 22%,transparent)}
.card.reviewing{border-color:var(--blue);box-shadow:0 0 0 2px color-mix(in srgb,var(--blue) 20%,transparent)}
.card[tabindex="0"]{cursor:pointer}
.card-title{font-weight:850;line-height:1.3;margin:7px 0 6px;overflow-wrap:anywhere}
.meta{color:var(--muted);font-size:13px;line-height:1.45;overflow-wrap:anywhere}
.meta strong{color:var(--soft)}
.tags{display:flex;gap:5px;flex-wrap:wrap;margin-top:8px}
.tag{
  display:inline-flex;align-items:center;min-height:22px;padding:2px 7px;
  border:1px solid var(--line);border-radius:8px;background:var(--panel);font-size:12px;
  color:var(--soft);font-weight:750;
}
.tag.green{background:color-mix(in srgb,var(--green) 18%,var(--panel));color:#bdf1d6}
.tag.blue{background:color-mix(in srgb,var(--blue) 18%,var(--panel));color:#cfe8ff}
.tag.gold{background:color-mix(in srgb,var(--gold) 18%,var(--panel));color:#ffe4a5}
.tag.red{background:color-mix(in srgb,var(--red) 18%,var(--panel));color:#ffd1d1}
.card-actions{display:flex;gap:7px;flex-wrap:wrap;margin-top:10px}
.select-row{
  display:flex;
  flex-direction:row;
  align-items:center;
  justify-content:flex-start;
  gap:8px;
  padding:8px;
  margin-top:10px;
  border:1px solid var(--line);
  border-radius:8px;
  background:var(--panel);
  color:var(--soft);
  text-transform:none;
  letter-spacing:0;
}
.select-row input{width:18px;height:18px;min-height:18px;accent-color:var(--green)}
.select-row span{font-size:13px;font-weight:800;color:var(--soft)}
.scan-tools{display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap;margin:4px 0 10px}
.scan-tools .fineprint{margin-right:auto}
.scan-log{display:flex;flex-direction:column;gap:6px;margin-bottom:10px}
.scan-row{
  width:100%;
  min-height:0;
  border:1px solid var(--line);
  border-radius:8px;
  background:var(--panel-2);
  color:var(--text);
  padding:10px;
  display:grid;
  grid-template-columns:92px minmax(112px,.55fr) minmax(0,1.4fr) auto;
  gap:10px;
  align-items:start;
  text-align:left;
  cursor:pointer;
}
.scan-history-pane .scan-row{grid-template-columns:70px minmax(92px,.5fr) minmax(0,1fr)}
.scan-history-pane .scan-counts{grid-column:1 / -1;justify-content:flex-start}
.scan-row:hover{border-color:var(--blue);text-decoration:none}
.scan-row.active{border-color:var(--green);box-shadow:0 0 0 2px color-mix(in srgb,var(--green) 20%,transparent)}
.scan-id{font-size:12px;font-weight:850;color:var(--soft)}
.scan-date{font-size:13px;font-weight:850;color:var(--text);line-height:1.25}
.scan-meta{font-size:12px;color:var(--muted);line-height:1.35;margin-top:2px}
.scan-summary{font-size:13px;color:var(--soft);line-height:1.35;overflow-wrap:anywhere}
.scan-counts{display:flex;gap:5px;flex-wrap:wrap;justify-content:flex-end}
.scan-counts .tag{white-space:nowrap}
.detail-pane[hidden],.default-pane[hidden]{display:none}
.detail-kicker{font-size:12px;color:var(--muted);font-weight:850;text-transform:uppercase;line-height:1.35;margin-bottom:4px}
.detail-title{font-size:17px;font-weight:900;line-height:1.25;margin-bottom:6px;overflow-wrap:anywhere}
.detail-tags{display:flex;gap:5px;flex-wrap:wrap;margin:8px 0 10px}
.detail-list{display:flex;flex-direction:column;gap:7px;margin:8px 0 12px}
.detail-row{
  display:grid;
  grid-template-columns:96px minmax(0,1fr);
  gap:8px;
  padding:8px;
  border:1px solid var(--line);
  border-radius:8px;
  background:var(--panel-2);
}
.detail-label{font-size:12px;color:var(--muted);font-weight:850;text-transform:uppercase;line-height:1.35}
.detail-value{font-size:13px;color:var(--soft);line-height:1.4;overflow-wrap:anywhere}
.detail-value.muted{color:var(--muted)}
.detail-section{margin-top:12px}
.detail-section h3{font-size:13px;margin:0 0 7px;color:var(--soft);text-transform:uppercase}
.detail-note{font-size:13px;color:var(--soft);line-height:1.45;overflow-wrap:anywhere}
.detail-note.muted{color:var(--muted)}
.detail-bullets{margin:0;padding-left:18px;color:var(--soft);font-size:13px;line-height:1.45}
.detail-bullets li{margin:0 0 6px}
.empty{border:1px dashed var(--line);border-radius:8px;padding:22px 12px;text-align:center;color:var(--muted)}
.summary{min-height:20px;color:var(--muted);font-size:13px;margin:8px 0}
.split{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.fineprint{font-size:12px;color:var(--muted);line-height:1.45}
.toast{
  position:fixed;right:18px;bottom:18px;z-index:20;display:none;
  max-width:min(360px,calc(100vw - 36px));background:var(--soft);color:var(--ink);
  border-radius:8px;padding:10px 12px;font-weight:800;box-shadow:0 12px 34px rgba(0,0,0,.28);
}
.toast.show{display:block}
.spinner{
  width:14px;height:14px;border-radius:50%;display:inline-block;vertical-align:-2px;margin-right:6px;
  border:2px solid color-mix(in srgb,var(--muted) 40%,transparent);border-top-color:var(--green);
  animation:spin .8s linear infinite;
}
@keyframes spin{to{transform:rotate(360deg)}}
@media (max-width:1100px){
  .grid{grid-template-columns:1fr 1fr}
  .scan-review{grid-column:1 / -1}
  .rightcol{grid-column:1 / -1}
  .stats{grid-template-columns:repeat(2,minmax(0,1fr))}
}
@media (max-width:760px){
  .shell{padding:12px}
  .topbar{margin:-12px -12px 12px;padding:12px}
  .toprow{align-items:flex-start}
  .brand h1{font-size:18px;white-space:normal}
  .brand p{font-size:12px}
  .statusline{display:none}
  .contextbar{align-items:flex-start;flex-direction:column}
  .grid,.split{grid-template-columns:1fr}
  .scan-review-grid{grid-template-columns:1fr}
  .scan-results-pane{border-left:0;border-top:1px solid var(--line);padding-left:0;padding-top:12px;position:static;max-height:none;overflow:visible}
  .buttonbar button{flex:1 1 auto}
  .scan-row{grid-template-columns:1fr}
  .scan-counts{justify-content:flex-start}
}
</style>
</head>
<body>
<main class="shell">
  <header class="topbar">
    <div class="toprow">
      <div class="brand">
        <div class="mark">SW</div>
        <div>
          <h1>Stormwind Contracting Bots</h1>
          <p>Field-installation leads, pursuits, setup work, and sub sourcing on one page.</p>
        </div>
      </div>
      <div class="spacer"></div>
      <div class="statusline">
        <span class="chip"><span class="dot"></span><span id="envLabel">loading</span></span>
        <span class="chip" id="profileLabel">technical services</span>
      </div>
    </div>
    <div class="contextbar">
      <div>
        <div class="context-title">Selected for this chat</div>
        <div class="context-value" id="selectedContextTitle">No contract selected</div>
      </div>
      <div class="context-note">Click "Use in chat" on a contract card, then come back here and refer to the selected contract.</div>
      <button class="small" type="button" onclick="clearSelectedContext()">Clear selection</button>
    </div>
    <div class="buttonbar">
      <button class="primary" type="button" onclick="runDigest()">Run scan</button>
      <button type="button" onclick="loadAll()">Refresh</button>
    </div>
  </header>

  <section class="stats">
    <button class="stat stat-button" type="button" onclick="scrollToPursuits()"><b id="statPursuits">--</b><span>pursuits</span></button>
    <div class="stat"><b id="statTasks">--</b><span>next steps</span></div>
    <div class="stat"><b id="statScans">--</b><span>scans</span></div>
  </section>

  <div class="grid">
    <section class="section scan-review">
      <div class="section-head">
        <h2>Scans</h2>
      </div>
      <div class="scan-review-grid">
        <div class="scan-history-pane">
          <div class="scan-tools">
            <span id="scanFolderCount" class="fineprint">Loading scans...</span>
            <button class="small" type="button" onclick="toggleScanOrder()" id="scanOrderButton">Oldest first</button>
          </div>
          <div class="scan-log" id="pastScans"><div class="empty">Loading scans...</div></div>
        </div>
        <div class="scan-results-pane">
          <div class="section-head">
            <h2>Opportunities</h2>
          </div>
          <div class="summary" id="searchSummary">Open a past scan or run a new scan.</div>
          <div class="results" id="searchResults"></div>
        </div>
      </div>
    </section>

    <section class="section side-panel" id="pursuitsPanel">
      <div class="default-pane" id="pursuitsPane">
        <div class="section-head">
          <h2>Pursuits</h2>
          <div class="section-actions">
            <select id="w-status" onchange="loadWatchlist()" style="width:auto;min-height:30px"></select>
          </div>
        </div>
        <div class="summary" id="watchSummary"></div>
        <div class="stack" id="watchlist"></div>
      </div>
      <div class="detail-pane" id="opportunityDetailPane" hidden>
        <div class="section-head">
          <h2>Opportunity details</h2>
          <div class="section-actions"><button class="small" type="button" onclick="clearOpportunityDetail()">Back</button></div>
        </div>
        <div id="opportunityDetail"><div class="empty">Click an opportunity to review the important dates, blockers, and next checks.</div></div>
      </div>
    </section>

    <section class="section rightcol">
      <div class="section-head">
        <h2>Next steps</h2>
        <div class="section-actions"><button class="small" onclick="loadTasks()">Refresh</button></div>
      </div>
      <div class="stack" id="tasks"></div>

      <hr style="border:0;border-top:1px solid var(--line);margin:14px 0">

      <div class="section-head">
        <h2>Source subs</h2>
      </div>
      <div class="split">
        <label>Service<input id="v-service" placeholder="CCTV install"></label>
        <label>Place<input id="v-place" placeholder="Northern Virginia"></label>
      </div>
      <div class="split" style="margin-top:8px">
        <label>NAICS<select id="v-naics"></select></label>
        <label>Due<input id="v-due" placeholder="YYYY-MM-DD"></label>
      </div>
      <div class="buttonbar">
        <button class="small primary" onclick="runVendorSourcing()">Generate</button>
      </div>
      <div class="summary" id="vendorSummary"></div>
      <div class="stack" id="vendorResults"></div>
    </section>
  </div>
</main>
<div class="toast" id="toast"></div>
<script>
const PROJECT_ROOT = __PROJECT_ROOT_JSON__;
const STATE = {
  profiles:["technical_services"],
  statuses:[],
  currentSearch:[],
  selectedNoticeId:null,
  reviewNoticeId:null,
  reviewOpportunity:null,
  scans:[],
  scanOrder:"asc",
  activeScanId:null
};
const PROFILE_LABELS = {
  technical_services:"technical services",
  elastic_only:"Elastic legacy"
};
const STATUS_LABELS = {
  tracking:"tracking",
  assessing:"assessing",
  pursuing:"pursuing",
  submitted:"submitted",
  won:"won",
  lost:"lost",
  withdrawn:"withdrawn",
  expired:"expired"
};
const STATUS_COLORS = {
  won:"green",
  submitted:"blue",
  pursuing:"blue",
  assessing:"gold",
  tracking:"",
  lost:"red",
  withdrawn:"red",
  expired:"red"
};

function esc(value){
  return String(value == null ? "" : value).replace(/[&<>"']/g, ch => ({
    "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"
  }[ch]));
}
async function api(path, options={}){
  const init = {headers:{"Content-Type":"application/json"}, ...options};
  if (init.body && typeof init.body !== "string") init.body = JSON.stringify(init.body);
  const response = await fetch(path, init);
  let data;
  try { data = await response.json(); } catch { data = {}; }
  if (!response.ok || data.error) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}
function toast(text){
  const el = document.getElementById("toast");
  el.textContent = text;
  el.classList.add("show");
  clearTimeout(window.__toastTimer);
  window.__toastTimer = setTimeout(() => el.classList.remove("show"), 2600);
}
function tag(text, color=""){ return `<span class="tag ${color}">${esc(text)}</span>`; }
function profileLabel(value){ return PROFILE_LABELS[value] || value || "profile"; }
function shortDate(value){ return value ? String(value).replace("T"," ").slice(0,16) : "-"; }
function scoreColor(band){
  if (band === "strong") return "green";
  if (band === "promising") return "blue";
  if (band === "monitor") return "gold";
  if (band === "reject") return "red";
  return "";
}
function workLocation(o){
  const bits = [o.pop_city, o.pop_state].filter(Boolean);
  return bits.length ? bits.join(", ") : (o.place || "");
}
function normalizeOpportunity(o){
  return {
    notice_id:o.notice_id,
    title:o.title,
    sol_number:o.sol_number,
    department:o.department,
    naics_code:o.naics_code,
    set_aside:o.set_aside,
    response_deadline:o.response_deadline,
    link:o.link
  };
}
function opportunityArg(o){
  return esc(JSON.stringify(o).replace(/'/g,"&#39;"));
}
function selectedClass(o){
  return STATE.selectedNoticeId && String(o.notice_id || "") === String(STATE.selectedNoticeId) ? " selected" : "";
}
function reviewClass(o){
  return STATE.reviewNoticeId && String(o.notice_id || "") === String(STATE.reviewNoticeId) ? " reviewing" : "";
}
function opportunityCardClass(o){
  return `card${selectedClass(o)}${reviewClass(o)}`;
}
function selectRow(o){
  const checked = STATE.selectedNoticeId && String(o.notice_id || "") === String(STATE.selectedNoticeId) ? "checked" : "";
  return `<label class="select-row" onclick="event.stopPropagation()">
    <input type="checkbox" ${checked} onchange='event.stopPropagation();selectForChat(${opportunityArg(o)})'>
    <span>Use in chat</span>
  </label>`;
}
function flattenText(value){
  if (Array.isArray(value)) return value.flatMap(flattenText);
  if (value && typeof value === "object") return Object.values(value).flatMap(flattenText);
  const text = String(value == null ? "" : value).trim();
  return text ? [text] : [];
}
function detailFragments(o){
  return [
    o.supported_fit,
    o.concern,
    o.blockers,
    o.evidence,
    o.delivery_read && o.delivery_read.detail,
    o.description
  ].flatMap(flattenText).filter(Boolean);
}
function compactNote(text, max=340){
  const clean = String(text || "").replace(/\s+/g, " ").trim();
  return clean.length > max ? `${clean.slice(0, max - 1)}...` : clean;
}
function splitDetailCandidates(text, includePairs=false){
  const clean = String(text || "")
    .replace(/\r/g, "\n")
    .replace(/[•·]/g, "\n")
    .replace(/\s+/g, " ")
    .trim();
  if (!clean) return [];
  const sentencePattern = /[^.!?]+[.!?]+|[^.!?]+$/g;
  const sentences = clean.match(sentencePattern) || [clean];
  if (!includePairs) return sentences.map(text => text.trim()).filter(Boolean);
  const candidates = [];
  for (let index = 0; index < sentences.length; index += 1) {
    const current = sentences[index].trim();
    if (!current) continue;
    const next = sentences[index + 1] ? sentences[index + 1].trim() : "";
    if (next && current.length < 180) {
      candidates.push(`${current} ${next}`);
    }
  }
  return candidates;
}
function findDetailNote(o, required){
  const fragments = detailFragments(o);
  const directCandidates = fragments.flatMap(text => splitDetailCandidates(text));
  const direct = directCandidates.find(text => required.every(pattern => pattern.test(text)));
  if (direct) return compactNote(direct);
  const pairedCandidates = fragments.flatMap(text => splitDetailCandidates(text, true));
  return compactNote(pairedCandidates.find(text => required.every(pattern => pattern.test(text))) || "");
}
function firstDetailNote(o, requiredSets){
  for (const required of requiredSets) {
    const note = findDetailNote(o, required);
    if (note) return note;
  }
  return "";
}
function listItems(value, limit=6){
  return flattenText(value).slice(0, limit);
}
function detailRow(label, value, muted=false){
  const text = value || "Not found in stored scan notes.";
  return `<div class="detail-row">
    <div class="detail-label">${esc(label)}</div>
    <div class="detail-value${muted || !value ? " muted" : ""}">${esc(text)}</div>
  </div>`;
}
function detailBullets(items, emptyText){
  const clean = (items || []).filter(Boolean);
  if (!clean.length) return `<div class="detail-note muted">${esc(emptyText)}</div>`;
  return `<ul class="detail-bullets">${clean.map(item => `<li>${esc(compactNote(item, 420))}</li>`).join("")}</ul>`;
}
function opportunityDetailHtml(o){
  const siteVisit = firstDetailNote(o, [
    [/site\s*visit|walkthrough|walk-through|bid\s*walk|pre-?bid/i],
  ]);
  const questions = firstDetailNote(o, [
    [/questions?|q&a|clarification/i, /due|deadline|no later|submitted|receive|by\s+\w+/i],
    [/questions?|q&a|clarification/i],
  ]);
  const submission = firstDetailNote(o, [
    [/email|portal|PIEE|SAM\.gov|sam\.gov|quote documents|quotes must|submission instructions/i],
    [/submit|submission|quotation|quote/i, /email|portal|PIEE|SAM\.gov|sam\.gov|via|through|address|mailto|subject line/i],
  ]);
  const disposition = o.delivery_read && o.delivery_read.label ? o.delivery_read.label : (o.disposition || "");
  const blockers = listItems(o.blockers, 6);
  const evidence = listItems(o.evidence, 6);
  const fitText = o.supported_fit || (o.delivery_read && o.delivery_read.detail) || "";
  return `<div>
    <div class="detail-kicker">${esc(o.notice_id || "opportunity")}</div>
    <div class="detail-title">${esc(o.title || "-")}</div>
    <div class="detail-tags">
      ${disposition ? tag(disposition, disposition.toLowerCase().includes("assess") ? "green" : "gold") : ""}
      ${o.band ? tag(o.band, scoreColor(o.band)) : ""}
      ${o.score != null ? tag(`score ${o.score}`) : ""}
      ${o.naics_code ? tag(o.naics_code) : ""}
    </div>
    <div class="buttonbar">
      <button class="small primary" type="button" onclick='selectForChat(${opportunityArg(o)})'>Use in chat</button>
      <button class="small" type="button" onclick='addToWatchlist(${opportunityArg(o)})'>Track</button>
      <button class="small" type="button" onclick='sourceSubsForOpportunity(${opportunityArg(o)})'>Source subs</button>
      ${o.link ? `<a class="btn small" target="_blank" href="${esc(o.link)}">Notice</a>` : ""}
    </div>
    <div class="detail-section">
      <h3>Critical dates</h3>
      <div class="detail-list">
        ${detailRow("Response due", shortDate(o.response_deadline))}
        ${detailRow("Posted", shortDate(o.posted_date))}
        ${detailRow("Site visit", siteVisit)}
        ${detailRow("Questions", questions)}
        ${detailRow("Submit via", submission)}
      </div>
    </div>
    <div class="detail-section">
      <h3>Notice facts</h3>
      <div class="detail-list">
        ${detailRow("Solicitation", o.sol_number || "-")}
        ${detailRow("Agency", o.department || o.sub_tier || "-")}
        ${detailRow("Set-aside", o.set_aside || "-")}
        ${detailRow("Place", workLocation(o) || "-")}
        ${detailRow("Deadline", o.deadline_note || "-")}
      </div>
    </div>
    <div class="detail-section">
      <h3>Fit read</h3>
      <div class="detail-note${fitText ? "" : " muted"}">${esc(fitText || "No supported-fit note stored for this scan item.")}</div>
      ${o.concern ? `<div class="detail-note" style="margin-top:8px"><strong>Concern:</strong> ${esc(o.concern)}</div>` : ""}
    </div>
    <div class="detail-section">
      <h3>Blockers / next checks</h3>
      ${detailBullets(blockers, o.concern || "No explicit blocker list stored. Verify dates, site visit, licensing, insurance, and submission instructions in the solicitation package.")}
    </div>
    <div class="detail-section">
      <h3>Evidence</h3>
      ${detailBullets(evidence, "No document evidence stored for this item yet.")}
    </div>
  </div>`;
}
function renderOpportunityDetail(){
  const defaultPane = document.getElementById("pursuitsPane");
  const detailPane = document.getElementById("opportunityDetailPane");
  const detail = document.getElementById("opportunityDetail");
  if (!STATE.reviewOpportunity) {
    defaultPane.hidden = false;
    detailPane.hidden = true;
    return;
  }
  defaultPane.hidden = true;
  detailPane.hidden = false;
  detail.innerHTML = opportunityDetailHtml(STATE.reviewOpportunity);
}
function showOpportunityDetail(o){
  STATE.reviewOpportunity = o;
  STATE.reviewNoticeId = o && o.notice_id ? String(o.notice_id) : null;
  renderOpportunityDetail();
  redrawVisibleCards();
  if (window.matchMedia("(max-width: 1100px)").matches) {
    document.getElementById("pursuitsPanel").scrollIntoView({behavior:"smooth", block:"start"});
  }
}
function clearOpportunityDetail(redraw=true){
  STATE.reviewOpportunity = null;
  STATE.reviewNoticeId = null;
  renderOpportunityDetail();
  if (redraw) redrawVisibleCards();
}
function leadCard(o){
  const reasons = (o.reasons || []).filter(r => r && r.label).slice(0,4).map(r => tag(`${r.weight > 0 ? "+" : ""}${r.weight} ${r.label}`, r.weight < 0 ? "red" : "green")).join("");
  const lanes = (o.lanes || []).filter(Boolean).slice(0,4).map(l => tag(l, "blue")).join("");
  const arg = opportunityArg(o);
  return `<article class="${opportunityCardClass(o)}" tabindex="0" onclick='showOpportunityDetail(${arg})' onkeydown='if(event.key==="Enter"||event.key===" "){event.preventDefault();showOpportunityDetail(${arg})}'>
    <div>${tag(o.band || "unscored", scoreColor(o.band))}${o.score != null ? tag(`score ${o.score}`) : ""}${o.naics_code ? tag(o.naics_code) : ""}</div>
    <div class="card-title">${esc(o.title || "-")}</div>
    <div class="meta"><strong>Due:</strong> ${esc(shortDate(o.response_deadline))} <strong>Agency:</strong> ${esc(o.department || o.sub_tier || "-")}</div>
    <div class="meta"><strong>Place:</strong> ${esc(workLocation(o) || "-")} <strong>Set-aside:</strong> ${esc(o.set_aside || "-")}</div>
    <div class="tags">${lanes}${reasons}</div>
    ${selectRow(o)}
    <div class="card-actions" onclick="event.stopPropagation()">
      <button class="small primary" onclick='addToWatchlist(${arg})'>Track</button>
      <button class="small" onclick='sourceSubsForOpportunity(${arg})'>Source subs</button>
      ${o.link ? `<a class="btn small" target="_blank" href="${esc(o.link)}">Notice</a>` : ""}
    </div>
  </article>`;
}
function watchCard(e){
  const status = e.status || "tracking";
  const arg = opportunityArg(e);
  return `<article class="${opportunityCardClass(e)}" tabindex="0" onclick='showOpportunityDetail(${arg})' onkeydown='if(event.key==="Enter"||event.key===" "){event.preventDefault();showOpportunityDetail(${arg})}'>
    <div>${tag(STATUS_LABELS[status] || status, STATUS_COLORS[status] || "")}${e.band ? tag(e.band, scoreColor(e.band)) : ""}${e.score != null ? tag(`score ${e.score}`) : ""}</div>
    <div class="card-title">${esc(e.title || "-")}</div>
    <div class="meta"><strong>Due:</strong> ${esc(shortDate(e.response_deadline))} <strong>NAICS:</strong> ${esc(e.naics_code || "-")}</div>
    <div class="meta"><strong>Notice:</strong> ${esc(e.notice_id || "-")} ${e.link ? `<a target="_blank" href="${esc(e.link)}" onclick="event.stopPropagation()">open</a>` : ""}</div>
    ${selectRow(e)}
    <div class="card-actions" onclick="event.stopPropagation()">
      <select onchange='changeStatus("${esc(e.notice_id)}", this.value)' style="width:auto;min-height:30px">
        ${STATE.statuses.map(s => `<option value="${esc(s)}" ${s === status ? "selected" : ""}>${esc(STATUS_LABELS[s] || s)}</option>`).join("")}
      </select>
      <button class="small" onclick='sourceSubsForOpportunity(${arg})'>Source subs</button>
      <button class="small" onclick='addNote("${esc(e.notice_id)}")'>Note</button>
      <button class="small danger" onclick='removeEntry("${esc(e.notice_id)}")'>Remove</button>
    </div>
  </article>`;
}
function taskCard(t){
  const color = t.priority === "high" ? "red" : (t.priority === "medium" ? "gold" : "");
  return `<article class="card">
    <div>${tag(t.status || "unknown")}${tag(t.priority || "medium", color)}${tag(t.effort || "M")}</div>
    <div class="card-title">${esc(t.title || t.id)}</div>
    <div class="meta"><strong>${esc(t.id)}</strong> ${esc(t.type || "")}</div>
    <div class="meta">${(t.dependencies || []).length ? `Depends on ${esc(t.dependencies.join(", "))}` : "No blockers listed."}</div>
  </article>`;
}
function scanTime(d){
  const date = new Date(d.run_at || "");
  return Number.isFinite(date.getTime()) ? date.getTime() : 0;
}
function scanDateParts(value){
  if (!value) return {date:"-", time:""};
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return {date:String(value).slice(0,10), time:String(value).slice(11,16)};
  return {
    date:date.toLocaleDateString([], {month:"short", day:"numeric", year:"numeric"}),
    time:date.toLocaleTimeString([], {hour:"numeric", minute:"2-digit"})
  };
}
function scanSummaryText(d){
  return d.summary || `${d.candidates_shown || 0} of ${d.candidates_scanned || 0} notices`;
}
function digestRow(d){
  const id = Number(d.id);
  const stamp = scanDateParts(d.run_at);
  const active = STATE.activeScanId === id ? " active" : "";
  return `<article class="scan-row${active}" onclick="openDigest(${id})" tabindex="0" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();openDigest(${id})}">
    <div>
      <div class="scan-id">scan ${id}</div>
      <div class="scan-meta">${esc(d.source || "digest")}</div>
    </div>
    <div>
      <div class="scan-date">${esc(stamp.date)}</div>
      <div class="scan-meta">${esc(stamp.time)}</div>
    </div>
    <div>
      <div class="scan-summary">${esc(scanSummaryText(d))}</div>
      <div class="scan-meta">${esc(profileLabel(d.profile))}</div>
    </div>
    <div class="scan-counts">
      ${tag(`${d.candidates_shown || 0} leads`, "blue")}
      ${tag(`${d.candidates_scanned || 0} scanned`)}
      ${d.report_path ? `<a class="btn small" target="_blank" href="/api/digest/report?id=${id}" onclick="event.stopPropagation()">Report</a>` : ""}
    </div>
  </article>`;
}
function renderScanHistory(){
  const ordered = [...STATE.scans].sort((a,b) => (
    STATE.scanOrder === "asc" ? scanTime(a) - scanTime(b) : scanTime(b) - scanTime(a)
  ));
  const countLabel = `${ordered.length} scan${ordered.length === 1 ? "" : "s"} · ${STATE.scanOrder === "asc" ? "oldest first" : "newest first"}`;
  document.getElementById("scanFolderCount").textContent = countLabel;
  document.getElementById("scanOrderButton").textContent = STATE.scanOrder === "asc" ? "Newest first" : "Oldest first";
  document.getElementById("pastScans").innerHTML = ordered.length ? ordered.map(digestRow).join("") : `<div class="empty">No scans yet.</div>`;
}
function toggleScanOrder(){
  STATE.scanOrder = STATE.scanOrder === "asc" ? "desc" : "asc";
  renderScanHistory();
}

function setCurrentContext(payload){
  const opportunity = payload && payload.opportunity;
  STATE.selectedNoticeId = opportunity && opportunity.notice_id ? String(opportunity.notice_id) : null;
  const title = document.getElementById("selectedContextTitle");
  if (!opportunity) {
    title.textContent = "No contract selected";
  } else {
    title.textContent = `${opportunity.notice_id} - ${opportunity.title || "selected contract"}`;
  }
}
async function loadSelectedContext(){
  const data = await api("/api/context/selected");
  setCurrentContext(data);
}
async function selectForChat(o){
  const data = await api("/api/context/select", {method:"POST", body:{opportunity:o}});
  setCurrentContext(data);
  redrawVisibleCards();
  toast("Selected for this chat");
}
async function clearSelectedContext(){
  const data = await api("/api/context/clear", {method:"POST", body:{}});
  setCurrentContext(data);
  redrawVisibleCards();
  toast("Selection cleared");
}
function redrawVisibleCards(){
  if (STATE.currentSearch.length) {
    document.getElementById("searchResults").innerHTML = STATE.currentSearch.map(leadCard).join("");
  }
  loadWatchlist().catch(()=>{});
}
function scrollToPursuits(){
  const panel = document.getElementById("pursuitsPanel");
  const topbar = document.querySelector(".topbar");
  const offset = (topbar ? topbar.getBoundingClientRect().height : 0) + 14;
  const top = window.scrollY + panel.getBoundingClientRect().top - offset;
  window.scrollTo({top: Math.max(0, top), behavior:"smooth"});
}

async function loadMeta(){
  const meta = await api("/api/profiles");
  STATE.profiles = meta.profiles || ["technical_services"];
  STATE.statuses = meta.statuses || [];
  document.getElementById("envLabel").textContent = `${(meta.env || "prod").toUpperCase()} local`;
  document.getElementById("profileLabel").textContent = profileLabel("technical_services");
  const statusSelect = document.getElementById("w-status");
  statusSelect.innerHTML = `<option value="">all</option>${STATE.statuses.map(s => `<option value="${esc(s)}">${esc(STATUS_LABELS[s] || s)}</option>`).join("")}`;
  const vendorMeta = await api("/api/vendors/profiles").catch(() => ({profiles:[]}));
  const vnaics = document.getElementById("v-naics");
  const profiles = vendorMeta.profiles && vendorMeta.profiles.length ? vendorMeta.profiles : [{naics:"561621",label:"Security systems"}];
  vnaics.innerHTML = profiles.map(p => `<option value="${esc(p.naics)}">${esc(p.naics)} - ${esc(p.label)}</option>`).join("");
}
async function loadAll(){
  await loadSelectedContext().catch(()=>{});
  await Promise.allSettled([loadWatchlist(), loadTasks(), loadDigests()]);
}
async function refreshStats(){
  const [watch, tasks, digests] = await Promise.all([
    api("/api/watchlist"),
    api("/api/tasks/unblocked?limit=20"),
    api("/api/digests")
  ]);
  document.getElementById("statPursuits").textContent = watch.length;
  document.getElementById("statTasks").textContent = tasks.length;
  document.getElementById("statScans").textContent = digests.length;
}
async function loadWatchlist(){
  const status = document.getElementById("w-status").value;
  const data = await api("/api/watchlist" + (status ? `?status=${encodeURIComponent(status)}` : ""));
  document.getElementById("watchSummary").textContent = `${data.length} pursuit${data.length === 1 ? "" : "s"}`;
  document.getElementById("watchlist").innerHTML = data.length ? data.map(watchCard).join("") : `<div class="empty">No pursuits yet.</div>`;
  await refreshStats().catch(()=>{});
}
async function loadTasks(){
  const data = await api("/api/tasks/unblocked?limit=5");
  document.getElementById("tasks").innerHTML = data.length ? data.map(taskCard).join("") : `<div class="empty">No unblocked setup tasks.</div>`;
  await refreshStats().catch(()=>{});
}
async function loadDigests(){
  const data = await api("/api/digests");
  STATE.scans = data || [];
  renderScanHistory();
  if (!STATE.currentSearch.length) {
    document.getElementById("searchSummary").textContent = "Open a past scan or run a new scan.";
    document.getElementById("searchResults").innerHTML = "";
  }
  await refreshStats().catch(()=>{});
}
async function openDigest(id){
  const target = document.getElementById("searchResults");
  document.getElementById("searchSummary").innerHTML = `<span class="spinner"></span>loading scan`;
  const data = await api(`/api/digest/items?id=${encodeURIComponent(id)}`);
  STATE.currentSearch = data.items || [];
  STATE.activeScanId = Number(id);
  clearOpportunityDetail(false);
  renderScanHistory();
  const run = STATE.scans.find(item => Number(item.id) === Number(id));
  const label = run ? `${scanDateParts(run.run_at).date} · ${scanSummaryText(run)}` : `scan ${id}`;
  document.getElementById("searchSummary").textContent = `${STATE.currentSearch.length} lead${STATE.currentSearch.length === 1 ? "" : "s"} from scan ${id} · ${label}`;
  target.innerHTML = STATE.currentSearch.length ? STATE.currentSearch.map(leadCard).join("") : `<div class="empty">This scan has no stored leads.</div>`;
  if (window.matchMedia("(max-width: 760px)").matches) {
    document.querySelector(".scan-results-pane").scrollIntoView({behavior:"smooth", block:"start"});
  }
}
async function addToWatchlist(o){
  await api("/api/watchlist", {
    method:"POST",
    body:{opportunity:normalizeOpportunity(o), status:"tracking", score:o.score, band:o.band, lanes:o.lanes || []}
  });
  toast("Added to pursuits");
  await loadWatchlist();
}
async function changeStatus(noticeId, status){
  await api("/api/watchlist/status", {method:"POST", body:{notice_id:noticeId, status}});
  toast("Status updated");
  await loadWatchlist();
}
async function addNote(noticeId){
  const text = prompt(`Note for ${noticeId}`);
  if (!text) return;
  await api("/api/watchlist/note", {method:"POST", body:{notice_id:noticeId, text}});
  toast("Note saved");
  await loadWatchlist();
}
async function removeEntry(noticeId){
  if (!confirm("Remove this pursuit?")) return;
  await api("/api/watchlist/remove", {method:"POST", body:{notice_id:noticeId}});
  toast("Removed");
  await loadWatchlist();
}
async function runDigest(){
  const summary = document.getElementById("searchSummary");
  summary.innerHTML = `<span class="spinner"></span>running scan`;
  try {
    const data = await api("/api/digest/run", {
      method:"POST",
      body:{profile:"technical_services", days:3, min_score:3, write:true}
    });
    STATE.currentSearch = data.items || [];
    clearOpportunityDetail(false);
    summary.textContent = `Scan complete: ${data.shown} leads from ${data.scanned} notices`;
    document.getElementById("searchResults").innerHTML = STATE.currentSearch.length ? STATE.currentSearch.map(leadCard).join("") : `<div class="empty">No strong leads in this scan.</div>`;
    await loadDigests();
  } catch (error) {
    summary.innerHTML = `<span style="color:var(--red)">${esc(error.message)}</span>`;
  }
}
async function runVendorSourcing(){
  const summary = document.getElementById("vendorSummary");
  summary.innerHTML = `<span class="spinner"></span>generating`;
  document.getElementById("vendorResults").innerHTML = "";
  try {
    const data = await api("/api/vendors/source", {
      method:"POST",
      body:{
        naics:document.getElementById("v-naics").value,
        service:document.getElementById("v-service").value,
        place:document.getElementById("v-place").value,
        due:document.getElementById("v-due").value,
        max_results:5
      }
    });
    summary.textContent = `${(data.vendors || []).length} vendors`;
    renderVendor(data);
  } catch (error) {
    summary.innerHTML = `<span style="color:var(--red)">${esc(error.message)}</span>`;
  }
}
async function sourceSubsForOpportunity(o){
  document.getElementById("v-service").value = o.title || "";
  document.getElementById("v-place").value = workLocation(o) || "DMV";
  document.getElementById("v-due").value = o.response_deadline || "";
  const sel = document.getElementById("v-naics");
  if (o.naics_code && [...sel.options].some(opt => opt.value === o.naics_code)) sel.value = o.naics_code;
  document.getElementById("vendorSummary").innerHTML = `<span class="spinner"></span>queueing pursuit sourcing`;
  try {
    const data = await api("/api/vendors/source-opportunity", {
      method:"POST",
      body:{opportunity:o, max_results:5}
    });
    document.getElementById("vendorSummary").textContent = `Queued ${data.job_id || "sourcing job"}`;
    renderVendor(data);
  } catch (error) {
    document.getElementById("vendorSummary").innerHTML = `<span style="color:var(--red)">${esc(error.message)}</span>`;
  }
}
function renderVendor(data){
  const vendors = (data.vendors || []).map(v => `<article class="card">
    <div class="card-title">${esc(v.name || "-")}</div>
    <div class="meta">${esc(v.address || v.formatted_address || "")}</div>
    <div class="meta">${esc(v.phone || v.website || "")}</div>
  </article>`).join("");
  const script = data.call_script ? `<article class="card"><div class="card-title">Call script</div><textarea readonly>${esc(data.call_script)}</textarea></article>` : "";
  const email = data.email_draft ? `<article class="card"><div class="card-title">Email draft</div><textarea readonly>${esc(data.email_draft)}</textarea></article>` : "";
  const report = data.report_download_url ? `<a class="btn small" href="${esc(data.report_download_url)}">Download report</a>` : "";
  document.getElementById("vendorResults").innerHTML = `${report}${vendors || `<div class="empty">No vendors returned.</div>`}${script}${email}`;
}
async function init(){
  const savedTheme = localStorage.getItem("swcb-theme");
  if (savedTheme) document.documentElement.dataset.theme = savedTheme;
  try {
    await loadMeta();
    await loadAll();
  } catch (error) {
    document.getElementById("searchSummary").innerHTML = `<span style="color:var(--red)">${esc(error.message)}</span>`;
  }
}
init();
</script>
</body>
</html>"""
