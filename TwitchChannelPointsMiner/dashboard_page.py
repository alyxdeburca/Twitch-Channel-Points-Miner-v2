# -*- coding: utf-8 -*-
# Embedded single-page dashboard served by dashboard_server.DashboardServer.
# Plain (raw) string on purpose: no f-strings, so JS template syntax stays intact.

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Twitch Miner Dashboard</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Ctext y='.9em' font-size='90'%3E%F0%9F%8E%AE%3C/text%3E%3C/svg%3E">
<style>
  :root {
    --bg: #0e0e10; --panel: #18181b; --panel2: #1f1f23; --border: #2f2f35;
    --text: #efeff1; --muted: #adadb8; --dim: #77777f;
    --accent: #a970ff; --accent2: #9147ff;
    --green: #22c55e; --red: #ef4444; --amber: #f59e0b; --blue: #3b82f6; --pink: #ec4899;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: var(--bg); color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    font-size: 14px; min-height: 100vh;
  }
  a { color: var(--accent); text-decoration: none; } a:hover { text-decoration: underline; }
  header {
    display: flex; align-items: center; gap: 12px; padding: 14px 22px;
    background: linear-gradient(90deg, #1a1024, var(--panel)); border-bottom: 1px solid var(--border);
    position: sticky; top: 0; z-index: 10;
  }
  .brand { font-size: 17px; font-weight: 700; letter-spacing: .2px; }
  .brand span { color: var(--accent); }
  .badge {
    font-size: 11px; padding: 3px 9px; border-radius: 999px; border: 1px solid var(--border);
    background: var(--panel2); color: var(--muted); white-space: nowrap;
  }
  .badge.demo { border-color: var(--amber); color: var(--amber); }
  .dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; vertical-align: middle; }
  .dot.on { background: var(--green); box-shadow: 0 0 6px var(--green); }
  .dot.off { background: var(--red); }
  #clock { margin-left: auto; color: var(--dim); font-size: 12px; font-variant-numeric: tabular-nums; }

  main { max-width: 1280px; margin: 0 auto; padding: 20px 22px 60px; }
  #stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin-bottom: 20px; }
  .stat {
    background: var(--panel); border: 1px solid var(--border); border-radius: 10px; padding: 14px 16px;
  }
  .stat .label { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: .8px; margin-bottom: 6px; }
  .stat .value { font-size: 24px; font-weight: 700; font-variant-numeric: tabular-nums; }
  .stat .sub { font-size: 11px; margin-top: 3px; color: var(--dim); }

  .grid { display: grid; grid-template-columns: 1fr 380px; gap: 16px; align-items: start; }
  @media (max-width: 980px) { .grid { grid-template-columns: 1fr; } }
  h2 { font-size: 12px; text-transform: uppercase; letter-spacing: 1px; color: var(--muted); margin-bottom: 10px; }
  section.panel h2 { padding: 0 2px; }

  #streamers { display: grid; grid-template-columns: repeat(auto-fill, minmax(290px, 1fr)); gap: 12px; }
  .card {
    background: var(--panel); border: 1px solid var(--border); border-radius: 10px; padding: 14px;
    transition: border-color .15s;
  }
  .card:hover { border-color: #4a4a52; }
  .card .top { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
  .avatar {
    width: 36px; height: 36px; border-radius: 50%; object-fit: cover;
    background: var(--panel2); border: 1px solid var(--border); flex: none;
  }
  .avatar-fallback {
    width: 36px; height: 36px; border-radius: 50%; flex: none;
    display: flex; align-items: center; justify-content: center;
    background: linear-gradient(135deg, #9147ff55, #a970ff33);
    border: 1px solid var(--border); color: var(--accent); font-weight: 700; font-size: 14px;
    text-transform: uppercase;
  }
  .card .name { font-weight: 700; font-size: 15px; }
  .card .online-tag { font-size: 10px; padding: 2px 7px; border-radius: 999px; font-weight: 600; }
  .online-tag.live { background: rgba(239,68,68,.15); color: var(--red); }
  .online-tag.off { background: rgba(119,119,127,.12); color: var(--dim); }
  .pts { font-size: 22px; font-weight: 700; font-variant-numeric: tabular-nums; }
  .gained { font-size: 12px; font-weight: 600; margin-left: 8px; }
  .gained.pos { color: var(--green); } .gained.neg { color: var(--red); } .gained.zero { color: var(--dim); }
  .stream-title {
    color: var(--muted); font-size: 12px; margin-top: 6px; overflow: hidden; text-overflow: ellipsis;
    display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
  }
  .meta { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
  .chip {
    font-size: 10px; padding: 2px 8px; border-radius: 999px; background: var(--panel2);
    border: 1px solid var(--border); color: var(--muted); white-space: nowrap;
  }
  .chip.on { color: var(--green); border-color: rgba(34,197,94,.35); }
  .chip.off { opacity: .55; }
  .history { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 10px; }
  .hchip { font-size: 10px; padding: 2px 7px; border-radius: 5px; background: var(--panel2); border: 1px solid var(--border); color: var(--muted); }
  .hchip b { color: var(--text); font-weight: 600; }
  .hchip .amt.pos { color: var(--green); } .hchip .amt.neg { color: var(--red); }

  aside { display: flex; flex-direction: column; gap: 16px; }
  .panel { background: var(--panel); border: 1px solid var(--border); border-radius: 10px; padding: 14px; }
  .bet { border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px; margin-bottom: 10px; background: var(--panel2); }
  .bet:last-child { margin-bottom: 0; }
  .bet .btop { display: flex; justify-content: space-between; gap: 8px; align-items: baseline; margin-bottom: 4px; }
  .bet .btitle { font-weight: 600; font-size: 13px; }
  .bet .bstreamer { color: var(--dim); font-size: 11px; }
  .status-pill { font-size: 9px; font-weight: 700; padding: 2px 7px; border-radius: 999px; letter-spacing: .5px; }
  .st-ACTIVE { background: rgba(34,197,94,.15); color: var(--green); }
  .st-BETPLACED, .st-CONFIRMED { background: rgba(169,112,255,.15); color: var(--accent); }
  .st-WIN { background: rgba(34,197,94,.15); color: var(--green); }
  .st-LOSE { background: rgba(239,68,68,.15); color: var(--red); }
  .st-REFUND { background: rgba(245,158,11,.15); color: var(--amber); }
  .st-RESOLVED { background: rgba(119,119,127,.15); color: var(--muted); }
  .countdown { color: var(--amber); font-size: 12px; font-weight: 700; font-variant-numeric: tabular-nums; }
  .decision { margin-top: 8px; font-size: 11px; color: var(--muted); }
  .decision b { color: var(--text); }
  .bar { display: flex; height: 14px; border-radius: 4px; overflow: hidden; margin-top: 8px; background: #26262b; }
  .bar > div { height: 100%; min-width: 2px; transition: width .4s ease; }
  .o-blue { background: var(--blue); } .o-pink { background: var(--pink); } .o-other { background: var(--accent2); }
  .olegend { display: flex; justify-content: space-between; font-size: 10px; color: var(--muted); margin-top: 4px; }
  .result-line { margin-top: 8px; font-size: 12px; font-weight: 700; }
  .result-line.pos { color: var(--green); } .result-line.neg { color: var(--red); }

  #events { list-style: none; max-height: 340px; overflow-y: auto; }
  #events li {
    font-size: 11px; padding: 6px 8px; border-left: 2px solid var(--border); margin-bottom: 6px;
    background: var(--panel2); border-radius: 0 6px 6px 0; color: var(--muted);
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    word-break: break-word; line-height: 1.45;
  }
  #events li .etype { color: var(--accent); font-weight: 700; }
  #events li .etime { color: var(--dim); margin-right: 6px; }
  .empty { color: var(--dim); font-size: 12px; padding: 10px 2px; }

  .panel-head { display:flex; align-items:center; justify-content:space-between; margin-bottom:10px; }
  .panel-head h2 { margin-bottom:0; }
  .btn {
    border:1px solid var(--border); background:var(--accent2); color:#fff; font-weight:700;
    padding:7px 14px; border-radius:8px; font-size:12px; cursor:pointer; transition:background .15s;
  }
  .btn:hover { background:var(--accent); }
  .card-remove {
    margin-left:auto; border:none; background:transparent; color:var(--dim); cursor:pointer;
    font-size:15px; line-height:1; padding:2px 6px; border-radius:5px;
  }
  .card-remove:hover { color:var(--red); background:rgba(239,68,68,.12); }
  #modal-backdrop {
    display:none; position:fixed; inset:0; background:rgba(0,0,0,.65); z-index:50;
    align-items:center; justify-content:center;
  }
  #modal-backdrop.open { display:flex; }
  .modal {
    background:var(--panel); border:1px solid var(--border); border-radius:12px;
    width:min(420px,92vw); padding:22px;
  }
  .modal h3 { font-size:16px; margin-bottom:6px; }
  .modal p { color:var(--muted); font-size:12px; line-height:1.55; margin-bottom:14px; }
  .modal input[type=text] {
    width:100%; padding:10px 12px; border-radius:8px; border:1px solid var(--border);
    background:var(--panel2); color:var(--text); font-size:14px; outline:none;
  }
  .modal input[type=text]:focus { border-color:var(--accent); }
  .modal-actions { display:flex; justify-content:flex-end; gap:8px; margin-top:16px; }
  .btn-secondary { background:var(--panel2); color:var(--text); }
  .btn-secondary:hover { background:#2a2a30; }
  #toast {
    position:fixed; bottom:42px; left:50%; transform:translateX(-50%); z-index:60;
    display:none; max-width:80vw; padding:10px 18px; border-radius:8px; font-size:13px; font-weight:600;
    border:1px solid var(--border); background:var(--panel2); box-shadow:0 6px 24px rgba(0,0,0,.5);
  }
  #toast.ok { border-color:rgba(34,197,94,.5); color:var(--green); }
  #toast.err { border-color:rgba(239,68,68,.5); color:var(--red); }
  #conn-error {
    display:none; margin-bottom:16px; padding:12px 16px; border-radius:10px;
    border:1px solid rgba(239,68,68,.5); background:rgba(239,68,68,.1);
    color:#fca5a5; font-size:13px; line-height:1.5;
  }
  .card-gear {
    border:none; background:transparent; color:var(--dim); cursor:pointer;
    font-size:14px; padding:2px 6px; border-radius:5px;
  }
  .card-gear:hover { color:var(--accent); background:rgba(169,112,255,.12); }
  .modal .form-grid {
    display:grid; grid-template-columns:1fr 1fr; gap:10px 14px;
    max-height:60vh; overflow-y:auto; padding-right:4px;
  }
  .modal label.fld { display:flex; flex-direction:column; gap:4px; font-size:11px; color:var(--muted); }
  .modal label.fld.full { grid-column:1 / -1; }
  .modal label.fld input[type=number],
  .modal label.fld select,
  .modal label.fld input[type=text] {
    padding:8px 10px; border-radius:7px; border:1px solid var(--border);
    background:var(--panel2); color:var(--text); font-size:13px; outline:none;
  }
  .modal label.fld input:focus, .modal label.fld select:focus { border-color:var(--accent); }
  .switch-row { display:flex; align-items:center; justify-content:space-between; gap:8px; }
  .switch { position:relative; width:34px; height:18px; flex:none; }
  .switch input { opacity:0; width:0; height:0; }
  .slider {
    position:absolute; cursor:pointer; inset:0; background:#3a3a42; border-radius:999px; transition:.15s;
  }
  .slider:before {
    content:""; position:absolute; height:14px; width:14px; left:2px; top:2px;
    background:#fff; border-radius:50%; transition:.15s;
  }
  .switch input:checked + .slider { background:var(--green); }
  .switch input:checked + .slider:before { transform:translateX(16px); }
  .settings-sep { grid-column:1 / -1; margin-top:6px; font-size:10px; letter-spacing:1px;
    text-transform:uppercase; color:var(--dim); border-bottom:1px solid var(--border); padding-bottom:4px; }

  footer { position: fixed; bottom: 0; left: 0; right: 0; text-align: center; padding: 6px;
    background: rgba(14,14,16,.85); backdrop-filter: blur(4px); color: var(--dim); font-size: 11px;
    border-top: 1px solid var(--border); }
</style>
</head>
<body>
<header>
  <div class="brand">🎮 <span>Twitch Miner</span> Dashboard</div>
  <span class="badge" id="user-badge">—</span>
  <span class="badge demo" id="demo-badge" style="display:none">DEMO DATA</span>
  <span class="badge"><span class="dot off" id="run-dot"></span><span id="run-label">stopped</span></span>
  <span id="clock"></span>
</header>

<main>
  <div id="conn-error"></div>
  <div id="stats"></div>
  <div class="grid">
    <section class="panel">
      <div class="panel-head"><h2>Streamers</h2><button class="btn" id="add-btn">＋ Add streamer</button></div>
      <div id="streamers"></div>
    </section>
    <aside>
      <section class="panel">
        <h2>Predictions &amp; Bets</h2>
        <div id="bets"></div>
      </section>
      <section class="panel">
        <h2>Event Feed</h2>
        <ul id="events"></ul>
      </section>
    </aside>
  </div>
</main>

<div id="modal-backdrop">
  <div class="modal">
    <h3>Add streamer</h3>
    <p>Enter the Twitch username to start mining. The miner validates the
    channel, loads its points context and subscribes to its events immediately.</p>
    <input type="text" id="new-username" placeholder="e.g. shroud" autocomplete="off" spellcheck="false">
    <div class="modal-actions">
      <button class="btn btn-secondary" id="cancel-add">Cancel</button>
      <button class="btn" id="confirm-add">Add</button>
    </div>
  </div>
</div>

<div id="settings-backdrop" style="display:none; position:fixed; inset:0; background:rgba(0,0,0,.65); z-index:55; align-items:center; justify-content:center;">
  <div class="modal" style="width:min(560px,94vw);">
    <h3>Settings — <span id="st-name"></span></h3>
    <p>Applied live to the running miner. Leave anything you don't want to change as-is.</p>
    <div class="form-grid" id="settings-form"></div>
    <div class="modal-actions">
      <button class="btn btn-secondary" id="cancel-settings">Cancel</button>
      <button class="btn" id="save-settings">Save settings</button>
    </div>
  </div>
</div>

<div id="toast"></div>

<footer><span id="upd">waiting for data…</span> · auto-refresh 3s</footer>

<script>
"use strict";
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g,
  (c) => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;" }[c]));
const fmt = (n) => Number(n || 0).toLocaleString("en-US");
const short = (n) => {
  n = Number(n || 0);
  const abs = Math.abs(n), sign = n < 0 ? "-" : "";
  if (abs >= 1e9) return sign + (abs/1e9).toFixed(2) + "B";
  if (abs >= 1e6) return sign + (abs/1e6).toFixed(2) + "M";
  if (abs >= 1e4) return sign + (abs/1e3).toFixed(1) + "K";
  return fmt(n);
};
const signed = (n) => (n > 0 ? "+" : "") + short(n);
const mmss = (s) => {
  s = Math.max(0, Math.round(s));
  const m = Math.floor(s/60), r = s % 60;
  return (m > 0 ? m + "m " : "") + (r < 10 && m > 0 ? "0" : "") + r + "s";
};
const oColor = (c) => (String(c||"").toLowerCase().includes("blue") ? "o-blue"
  : String(c||"").toLowerCase().includes("pink") ? "o-pink" : "o-other");
let deadlines = {};

function renderAll(d) {
  $("demo-badge").style.display = d.status.demo ? "" : "none";
  $("user-badge").textContent = "@" + (d.status.username || "unknown");
  const run = !!d.status.running;
  $("run-dot").className = "dot " + (run ? "on" : "off");
  $("run-label").textContent = d.status.demo ? "demo" : (run ? "mining" : "stopped");

  const gainedTotal = d.streamers.reduce((a, s) => a + (s.points_gained || 0), 0);
  $("stats").innerHTML = [
    ["Total Channel Points", short(d.status.total_points), fmt(d.status.total_points) + " pts"],
    ["Streamers Online", d.status.online_count + " / " + d.status.streamer_count,
      d.status.streamer_count + " tracked"],
    ["Active Bets", d.status.active_bets, d.status.active_bets ? "predictions running" : "none open"],
    ["Session Gain", signed(gainedTotal), "across all channels"],
  ].map(([l, v, sub]) =>
    `<div class="stat"><div class="label">${esc(l)}</div><div class="value">${esc(v)}</div><div class="sub">${esc(sub)}</div></div>`
  ).join("");

  // streamers: online first, then by points desc
  const sts = [...d.streamers].sort((a, b) =>
    (b.online - a.online) || (b.channel_points - a.channel_points));
  $("streamers").innerHTML = sts.length ? sts.map((s) => {
    const gcls = s.points_gained > 0 ? "pos" : (s.points_gained < 0 ? "neg" : "zero");
    const chips = [
      ["predictions", s.settings.make_predictions], ["raid", s.settings.follow_raid],
      ["drops", s.settings.claim_drops], ["streak", s.settings.watch_streak],
      ["chat", s.chat],
    ].map(([k, v]) => `<span class="chip ${v ? "on" : "off"}">${k}</span>`).join("");
    const hist = Object.entries(s.history || {})
      .sort((a, b) => Math.abs(b[1].amount) - Math.abs(a[1].amount))
      .map(([k, v]) =>
        `<span class="hchip">${esc(k)} ×${v.counter} <span class="amt ${v.amount >= 0 ? "pos" : "neg"}">${signed(v.amount)}</span></span>`)
      .join("");
    return `<div class="card">
    <div class="top">
      <img class="avatar" src="/avatars/${esc(s.username)}" alt=""
           onerror="this.outerHTML='<div class=&quot;avatar-fallback&quot;>${esc((s.username||'?')[0])}</div>'">
      <a class="name" href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.username)}</a>
      <span class="online-tag ${s.online ? "live" : "off"}">${s.online ? "LIVE" : "OFFLINE"}</span>
      <button class="card-gear" title="Settings for ${esc(s.username)}" data-settings="${esc(s.username)}">⚙</button>
      <button class="card-remove" title="Stop tracking ${esc(s.username)}" data-rm="${esc(s.username)}">✕</button>
    </div>
      <div><span class="pts">${short(s.channel_points)}</span>
        <span class="gained ${gcls}">${signed(s.points_gained)} this session</span></div>
      ${s.online && s.title ? `<div class="stream-title">${esc(s.title)}</div>` : ""}
      <div class="meta">
        ${s.online ? `<span class="chip">👁 ${short(s.viewers)}</span>` : ""}
        ${s.online && s.game ? `<span class="chip">${esc(s.game)}</span>` : ""}
        ${s.multipliers ? `<span class="chip">×${s.multipliers} mult</span>` : ""}
        ${s.settings.bet.strategy ? `<span class="chip">🎯 ${esc(s.settings.bet.strategy)}</span>` : ""}
      </div>
      ${hist ? `<div class="history">${hist}</div>` : ""}
    </div>`;
  }).join("") : `<div class="empty">No streamers tracked yet.</div>`;

  // bets: active first, resolved below
  const rank = { "ACTIVE": 0, "CONFIRMED": 1, "BET PLACED": 2, "RESOLVED": 3 };
  const bets = [...d.bets].sort((a, b) => (rank[a.status] ?? 9) - (rank[b.status] ?? 9));
  const newDeadlines = {};
  $("bets").innerHTML = bets.length ? bets.map((b, i) => {
    const totalPts = (b.outcomes || []).reduce((a, o) => a + (o.points || 0), 0) || 1;
    let bars = "", legend = "";
    if ((b.outcomes || []).length === 2) {
      bars = `<div class="bar">` + b.outcomes.map((o) =>
        `<div class="${oColor(o.color)}" style="width:${Math.max(2, 100*(o.points||0)/totalPts)}%" title="${esc(o.title)}: ${fmt(o.points)} pts"></div>`
      ).join("") + `</div>`;
      legend = `<div class="olegend">` + b.outcomes.map((o) =>
        `<span>${esc(o.title)} · ${o.percentage_users || 0}% users · ${(o.odds_percentage || 0).toFixed ? (o.odds_percentage||0).toFixed(1) : (o.odds_percentage||0)}%</span>`
      ).join("") + `</div>`;
    }
    const dec = b.decision && b.decision.choice
      ? `<div class="decision">Bot picks <b>${esc(b.decision.choice)} — ${esc(b.decision.title || "")}</b> (${fmt(b.decision.amount)} pts)</div>` : "";
    const res = b.result && b.result.type
      ? `<div class="result-line ${b.result.gained >= 0 ? "pos" : "neg"}">${esc(b.result.type)} · ${signed(b.result.gained)} pts</div>` : "";
    const cd = (b.status === "ACTIVE" && b.closed_in > 0)
      ? `<span class="countdown" data-cd="${i}">⏳ ${mmss(b.closed_in)}</span>` : "";
    if (b.status === "ACTIVE" && b.closed_in > 0) newDeadlines[i] = Date.now() + b.closed_in * 1000;
    return `<div class="bet">
      <div class="btop"><div><div class="btitle">${esc(b.title)}</div>
        <div class="bstreamer">@${esc(b.streamer)} · ${short(b.total_points)} pts · ${fmt(b.total_users)} users</div></div>
        <div style="text-align:right">${cd}<br><span class="status-pill st-${esc(String(b.status).replace(/ /g, ""))}">${esc(b.status)}</span></div></div>
      ${bars}${legend}${dec}${res}
    </div>`;
  }).join("") : `<div class="empty">No predictions yet.</div>`;
  deadlines = newDeadlines;

  // events
  $("events").innerHTML = d.events.length ? [...d.events].reverse().slice(-40).map((e) => {
    if (e.raw != null) return `<li>${esc(e.raw)}</li>`;
    return `<li><span class="etime">${new Date(e.time * 1000).toLocaleTimeString()}</span><span class="etype">${esc(e.type)}</span> — ${esc(e.text)}</li>`;
  }).join("") : `<div class="empty">Waiting for events…</div>`;

  $("upd").textContent = "updated " + new Date().toLocaleTimeString() +
    (d.status.demo ? " · demo data, no miner attached" : "");

  window.__editable = !!(d.config && d.config.editable);
  window.__options = (d.config && d.config.options) || {};
  window.__streamerIndex = {};
  d.streamers.forEach((s) => { window.__streamerIndex[s.username] = s; });
}

// ---------- streamer management ---------- //
let toastTimer = null;
function toast(msg, ok) {
  const el = $("toast");
  el.textContent = msg;
  el.className = ok ? "ok" : "err";
  el.style.display = "block";
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.style.display = "none"; }, 4000);
}
async function postJSON(url, body) {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  let data = {};
  try { data = await r.json(); } catch (e) {}
  if (!r.ok) throw new Error(data.error || ("HTTP " + r.status));
  return data;
}
async function addStreamer(username) {
  try {
    await postJSON("/api/streamers/add", { username });
    toast("Now tracking " + username, true);
    tick();
    return true;
  } catch (err) {
    toast("Could not add " + username + ": " + err.message, false);
    return false;
  }
}
async function removeStreamer(username) {
  if (!confirm("Stop tracking " + username + "?")) return;
  try {
    await postJSON("/api/streamers/remove", { username });
    toast("Stopped tracking " + username, true);
    tick();
  } catch (err) {
    toast("Could not remove " + username + ": " + err.message, false);
  }
}
$("add-btn").addEventListener("click", () => {
  $("modal-backdrop").classList.add("open");
  $("new-username").value = "";
  $("new-username").focus();
});
$("cancel-add").addEventListener("click", () => $("modal-backdrop").classList.remove("open"));
$("modal-backdrop").addEventListener("click", (e) => {
  if (e.target === $("modal-backdrop")) $("modal-backdrop").classList.remove("open");
});
$("confirm-add").addEventListener("click", async () => {
  const name = $("new-username").value.trim().toLowerCase();
  if (!name) return;
  const ok = await addStreamer(name);
  if (ok) $("modal-backdrop").classList.remove("open");
});
$("new-username").addEventListener("keydown", (e) => {
  if (e.key === "Enter") $("confirm-add").click();
  if (e.key === "Escape") $("modal-backdrop").classList.remove("open");
});
document.addEventListener("click", (e) => {
  const rm = e.target.closest("[data-rm]");
  if (rm) removeStreamer(rm.dataset.rm);
  const gear = e.target.closest("[data-settings]");
  if (gear) {
    const s = window.__streamerIndex && window.__streamerIndex[gear.dataset.settings];
    if (s) openSettings(s);
  }
});

// ---------- settings editor ---------- //
function swRow(key, label, checked) {
  return `<div class="fld full switch-row" style="border:1px solid var(--border); border-radius:8px; padding:8px 12px; background:var(--panel2);">
    <span>${esc(label)}</span>
    <label class="switch"><input type="checkbox" data-set="${key}" ${checked ? "checked" : ""}><span class="slider"></span></label>
  </div>`;
}
function openSettings(s) {
  const opts = (window.__options || {});
  const b = (s.settings && s.settings.bet) || {};
  const fc = b.filter_condition;
  $("st-name").textContent = "@" + s.username;

  const sel = (key, list, val) =>
    `<select data-set="${key}">` + list.map((o) =>
      `<option value="${o}" ${String(val).toUpperCase() === o ? "selected" : ""}>${o}</option>`
    ).join("") + `</select>`;

  $("settings-form").innerHTML = [
    `<div class="settings-sep">Mining</div>`,
    swRow("make_predictions", "Make predictions (bet)", s.settings.make_predictions),
    swRow("follow_raid", "Follow raids", s.settings.follow_raid),
    swRow("claim_drops", "Claim drops", s.settings.claim_drops),
    swRow("watch_streak", "Watch streak priority", s.settings.watch_streak),
    `<label class="fld">Chat presence${sel("chat", opts.chat || ["ALWAYS","NEVER","ONLINE","OFFLINE"], s.settings.chat || "NEVER")}</label>`,
    `<div class="settings-sep">Betting</div>`,
    `<label class="fld">Strategy${sel("strategy", opts.strategy || ["MOST_VOTED","HIGH_ODDS","PERCENTAGE","SMART_MONEY","SMART"], b.strategy || "SMART")}</label>`,
    `<label class="fld">Bet % of points<input type="number" min="1" max="100" data-set="percentage" value="${b.percentage ?? 5}"></label>`,
    `<label class="fld">SMART gap %<input type="number" min="0" max="100" data-set="percentage_gap" value="${b.percentage_gap ?? 20}"></label>`,
    `<label class="fld">Max bet points<input type="number" min="0" data-set="max_points" value="${b.max_points ?? 50000}"></label>`,
    `<label class="fld">Minimum points to bet<input type="number" min="0" data-set="minimum_points" value="${b.minimum_points ?? 0}"></label>`,
    swRow("stealth_mode", "Stealth mode", b.stealth_mode),
    `<label class="fld">Delay (seconds)<input type="number" min="0" max="1200" step="0.5" data-set="delay" value="${b.delay ?? 6}"></label>`,
    `<label class="fld">Delay mode${sel("delay_mode", opts.delay_mode || ["FROM_START","FROM_END","PERCENTAGE"], b.delay_mode || "FROM_END")}</label>`,
    `<div class="settings-sep">Filter condition (skip bets unless matched)</div>`,
    `<label class="fld">Filter by${sel("filter_by", opts.filter_by || ["NONE","PERCENTAGE_USERS","ODDS_PERCENTAGE","ODDS","TOP_POINTS","TOTAL_USERS","TOTAL_POINTS"], fc ? fc.by : "NONE")}</label>`,
    `<label class="fld">Condition${sel("filter_where", opts.filter_where || ["GT","LT","GTE","LTE"], fc ? fc.where : "LTE")}</label>`,
    `<label class="fld">Value<input type="number" step="any" data-set="filter_value" value="${fc ? fc.value : 800}"></label>`,
  ].join("");

  $("settings-backdrop").style.display = "flex";
}
function closeSettings() { $("settings-backdrop").style.display = "none"; }
$("cancel-settings").addEventListener("click", closeSettings);
$("settings-backdrop").addEventListener("click", (e) => {
  if (e.target === $("settings-backdrop")) closeSettings();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeSettings();
});
$("save-settings").addEventListener("click", async () => {
  const name = $("st-name").textContent.replace(/^@/, "");
  const get = (k) => document.querySelector(`#settings-form [data-set="${k}"]`);
  const num = (k, def = null) => {
    const el = get(k);
    return el && el.value !== "" ? Number(el.value) : def;
  };
  const payload = {
    username: name,
    settings: {
      make_predictions: get("make_predictions").checked,
      follow_raid: get("follow_raid").checked,
      claim_drops: get("claim_drops").checked,
      watch_streak: get("watch_streak").checked,
      chat: get("chat").value,
      bet: {
        strategy: get("strategy").value,
        percentage: num("percentage"),
        percentage_gap: num("percentage_gap"),
        max_points: num("max_points"),
        minimum_points: num("minimum_points"),
        stealth_mode: get("stealth_mode").checked,
        delay: num("delay"),
        delay_mode: get("delay_mode").value,
        filter_condition:
          get("filter_by").value === "NONE"
            ? null
            : {
                by: get("filter_by").value,
                where: get("filter_where").value,
                value: num("filter_value", 0),
              },
      },
    },
  };
  try {
    await postJSON("/api/streamers/settings", payload);
    toast("Settings saved for @" + name, true);
    closeSettings();
    tick();
  } catch (err) {
    toast("Could not save settings: " + err.message, false);
  }
});

setInterval(() => {
  document.querySelectorAll(".countdown").forEach((el) => {
    const dl = deadlines[el.dataset.cd];
    if (!dl) return;
    const left = (dl - Date.now()) / 1000;
    el.textContent = "⏳ " + mmss(left);
  });
}, 1000);

async function tick() {
  try {
    const r = await fetch("/api/all");
    if (!r.ok) throw new Error("HTTP " + r.status);
    const data = await r.json();
    renderAll(data);
    $("conn-error").style.display = "none";
  } catch (err) {
    const el = $("conn-error");
    el.style.display = "block";
    el.innerHTML = "⚠ Can't reach the miner API (" + esc(String(err.message || err)) +
      "). The page will keep retrying every 3s. If this persists, update the repo " +
      "(git pull) and restart the miner — check its console for errors.";
  }
}
tick();
setInterval(tick, 3000);

const clockEl = $("clock");
setInterval(() => { clockEl.textContent = new Date().toLocaleTimeString(); }, 1000);
</script>
</body>
</html>
"""
