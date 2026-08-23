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
  <div id="stats"></div>
  <div class="grid">
    <section class="panel">
      <h2>Streamers</h2>
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
        <span class="dot ${s.online ? "on" : "off"}"></span>
        <a class="name" href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.username)}</a>
        <span class="online-tag ${s.online ? "live" : "off"}">${s.online ? "LIVE" : "OFFLINE"}</span>
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
}

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
    if (!r.ok) throw new Error(r.status);
    renderAll(await r.json());
  } catch (err) {
    $("upd").textContent = "connection error — retrying…";
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
