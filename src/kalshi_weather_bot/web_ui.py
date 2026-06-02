from __future__ import annotations

import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv

from .calibration import compute_calibration
from .config import Settings
from .fees import FeeModel
from .paper import PaperTrader
from .shadow import ProductionShadowTracker
from .storage import Store, _is_postgres_target

DEFAULT_DB = "data/kalshi_weather.sqlite"

HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Kalshi Weather Desk</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: oklch(0.155 0.018 255);
      --paper: oklch(0.205 0.022 255);
      --panel: oklch(0.255 0.026 255);
      --panel-2: oklch(0.31 0.03 255);
      --ink: oklch(0.925 0.012 255);
      --muted: oklch(0.69 0.018 255);
      --line: oklch(0.36 0.03 255);
      --line-strong: oklch(0.48 0.038 255);
      --green: oklch(0.72 0.14 154);
      --red: oklch(0.68 0.15 27);
      --amber: oklch(0.76 0.13 76);
      --blue: oklch(0.72 0.12 230);
      --violet: oklch(0.73 0.13 295);
      --shadow: 0 18px 55px oklch(0.06 0.02 255 / 0.35);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      color: var(--ink);
      background:
        radial-gradient(circle at 8% 0%, oklch(0.30 0.06 230), transparent 34rem),
        radial-gradient(circle at 88% 12%, oklch(0.28 0.045 154), transparent 30rem),
        linear-gradient(180deg, var(--bg), oklch(0.12 0.016 255));
      font-family: ui-sans-serif, Inter, Avenir Next, Segoe UI, system-ui, sans-serif;
    }
    .shell { min-height: 100vh; display: grid; grid-template-columns: 258px minmax(0, 1fr); }
    aside {
      position: sticky; top: 0; height: 100vh; padding: 24px 18px;
      background: oklch(0.115 0.018 255); color: var(--ink);
      border-right: 1px solid var(--line);
    }
    .brand { display: flex; align-items: center; gap: 12px; margin-bottom: 26px; }
    .mark { width: 36px; height: 36px; border-radius: 14px; background: linear-gradient(135deg, var(--amber), oklch(0.64 0.11 154)); box-shadow: 0 10px 28px oklch(0.12 0.02 72 / .28); }
    .brand b { display: block; font-size: 15px; letter-spacing: -0.02em; }
    .brand span { display: block; color: var(--muted); font-size: 12px; margin-top: 2px; }
    nav { display: grid; gap: 6px; }
    nav button {
      text-align: left; border: 0; border-radius: 14px; padding: 11px 12px; color: oklch(0.82 0.018 91);
      background: transparent; font: inherit; cursor: pointer;
    }
    nav button:hover { background: oklch(0.22 0.024 255); color: var(--ink); }
    nav button.active { background: var(--panel); color: var(--ink); font-weight: 750; }
    .side-note { position: absolute; left: 18px; right: 18px; bottom: 20px; color: var(--muted); font-size: 12px; line-height: 1.45; }
    main { padding: 30px clamp(18px, 3vw, 42px) 64px; max-width: 1440px; width: 100%; }
    .topbar { display: flex; justify-content: space-between; gap: 18px; align-items: start; margin-bottom: 24px; }
    h1 { margin: 0; font-size: clamp(34px, 5vw, 62px); line-height: .94; letter-spacing: -0.065em; max-width: 760px; }
    .lede { max-width: 70ch; color: var(--muted); line-height: 1.5; margin: 14px 0 0; }
    .actions { display: flex; gap: 8px; flex-wrap: wrap; justify-content: end; }
    button, input {
      border: 1px solid var(--line); background: var(--paper); color: var(--ink); border-radius: 13px;
      padding: 10px 12px; font: inherit;
    }
    input { width: 92px; }
    button { cursor: pointer; transition: transform .16s cubic-bezier(.16,1,.3,1), background .16s; }
    button:hover { transform: translateY(-1px); background: var(--panel); }
    button.primary { background: var(--ink); color: oklch(0.96 0.01 91); border-color: var(--ink); font-weight: 800; }
    button.live { background: oklch(0.88 0.08 154); border-color: oklch(0.72 0.09 154); font-weight: 800; }
    .status { min-height: 20px; text-align: right; color: var(--muted); font-size: 13px; margin-top: 9px; }
    .page { display: none; }
    .page.active { display: block; animation: in .22s cubic-bezier(.16,1,.3,1); }
    @keyframes in { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
    .metric-strip { display: grid; grid-template-columns: repeat(6, minmax(0,1fr)); gap: 10px; margin: 22px 0 20px; }
    .metric {
      padding: 15px 16px 14px; border: 1px solid var(--line); border-radius: 18px; background: color-mix(in oklch, var(--paper) 88%, transparent);
      box-shadow: 0 10px 28px oklch(0.38 0.03 72 / .06);
    }
    .metric b { display: block; font-size: clamp(28px, 2.6vw, 36px); letter-spacing: -0.045em; margin-bottom: 5px; line-height: 0.95; font-variant-numeric: tabular-nums; white-space: nowrap; }
    .metric span { color: var(--muted); font-size: 13px; }
    .metric b span { color: inherit; font-size: inherit; line-height: inherit; }
    .stack { display: grid; gap: 16px; }
    .grid { display: grid; grid-template-columns: repeat(12, minmax(0,1fr)); gap: 16px; align-items: start; }
    section.panel { grid-column: span 6; background: var(--paper); border: 1px solid var(--line); border-radius: 24px; overflow: hidden; box-shadow: var(--shadow); }
    section.wide { grid-column: 1 / -1; }
    section.third { grid-column: span 4; }
    section h2 { margin: 0; padding: 18px 18px 9px; font-size: 17px; letter-spacing: -0.025em; }
    .hint { color: var(--muted); font-size: 12px; padding: 0 18px 14px; }
    table { width: 100%; border-collapse: collapse; font-size: 13px; }
    th, td { text-align: left; padding: 10px 14px; border-top: 1px solid color-mix(in oklch, var(--line) 72%, transparent); vertical-align: top; }
    th { color: var(--muted); font-weight: 680; white-space: nowrap; }
    td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
    .ticker { font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: 12px; }
    .pill { display: inline-flex; align-items: center; border: 1px solid var(--line); border-radius: 999px; padding: 3px 8px; color: var(--muted); background: var(--panel); font-size: 12px; white-space: nowrap; }
    .good { color: var(--green); font-weight: 850; } .warn { color: var(--amber); font-weight: 850; } .bad { color: var(--red); font-weight: 850; } .blue { color: var(--blue); font-weight: 850; }
    .empty { color: var(--muted); padding: 0 18px 18px; }
    .chart { height: 230px; padding: 4px 14px 16px; }
    .chart svg { width: 100%; height: 100%; display: block; overflow: visible; }
    .axis { stroke: var(--line); stroke-width: 1; }
    .line { fill: none; stroke: var(--blue); stroke-width: 3; stroke-linecap: round; stroke-linejoin: round; }
    .line.green { stroke: var(--green); } .line.red { stroke: var(--red); }
    .bar { fill: color-mix(in oklch, var(--blue) 74%, var(--paper)); }
    .bar.green { fill: var(--green); } .bar.amber { fill: var(--amber); } .bar.red { fill: var(--red); }
    .chart-label { fill: var(--muted); font-size: 11px; }
    .split { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
    .callout { padding: 18px; border-top: 1px solid var(--line); color: var(--muted); line-height: 1.5; }
    @media (max-width: 980px) {
      .shell { display: block; }
      aside { position: static; height: auto; }
      .side-note { position: static; margin-top: 18px; }
      nav { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .topbar { display: block; }
      .actions { justify-content: start; margin-top: 18px; }
      .metric-strip { grid-template-columns: repeat(2, minmax(0,1fr)); }
      section.panel, section.third { grid-column: 1 / -1; }
      .split { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
<div class="shell">
  <aside>
    <div class="brand"><div class="mark"></div><div><b>Weather Desk</b><span>Kalshi shadow control</span></div></div>
    <nav id="nav"></nav>
    <div class="side-note">Production shadow mode records what the bot would buy. It does not submit live orders.</div>
  </aside>
  <main>
    <div class="topbar">
      <div>
        <h1 id="pageTitle">Home</h1>
        <p class="lede" id="pageLede">A quick read on whether the strategy is seeing live, executable weather edges.</p>
      </div>
      <div>
        <div class="actions">
          <label>Limit <input id="limit" type="number" min="1" max="1000" value="50"></label>
          <button onclick="refresh()">Refresh</button>
          <button onclick="runPaper()">Paper scan</button>
          <button class="live" onclick="runShadow()">Shadow scan</button>
        </div>
        <div class="status" id="status"></div>
      </div>
    </div>

    <div id="home" class="page active">
      <div class="metric-strip" id="metrics"></div>
      <div class="grid">
        <section class="panel wide"><h2>Bot health timeline</h2><div class="hint">Scans, production snapshots, shadow fills, and local paper fills by hour.</div><div class="chart" id="runChart"></div></section>
        <section class="panel third"><h2>Production fillability</h2><div class="chart" id="fillabilityChart"></div></section>
        <section class="panel third"><h2>Shadow P/L curve</h2><div class="chart" id="shadowPnlChart"></div></section>
        <section class="panel third"><h2>Latest status</h2><div id="latestStatus"></div></section>
      </div>
    </div>

    <div id="scans" class="page">
      <div class="grid">
        <section class="panel wide"><h2>Recent scan runs</h2><div id="scanRuns"></div></section>
        <section class="panel"><h2>Local paper skip reasons</h2><div id="paperSkips"></div></section>
        <section class="panel"><h2>Production skip reasons</h2><div id="shadowSkips"></div></section>
        <section class="panel"><h2>Selected side mix</h2><div class="chart" id="sideChart"></div></section>
        <section class="panel"><h2>Shadow side mix</h2><div class="chart" id="shadowSideChart"></div></section>
      </div>
    </div>

    <div id="open" class="page">
      <div class="grid">
        <section class="panel wide"><h2>Current open shadow bids</h2><div class="hint">These are simulated fills still waiting for settlement.</div><div id="openShadow"></div></section>
        <section class="panel wide"><h2>Open local paper positions</h2><div id="positions"></div></section>
        <section class="panel wide"><h2>Recent production quote snapshots</h2><div id="shadowSnapshots"></div></section>
      </div>
    </div>

    <div id="settled" class="page">
      <div class="grid">
        <section class="panel wide"><h2>Settled shadow contracts</h2><div id="settledShadow"></div></section>
        <section class="panel"><h2>Shadow P/L by side</h2><div id="shadowPnlBySide"></div></section>
        <section class="panel"><h2>Paper P/L by side</h2><div id="pnlBySide"></div></section>
        <section class="panel wide"><h2>Model calibration</h2><div class="hint">Are the model's probabilities trustworthy? Predicted should match actual; lower Brier is better. Same-day (leakage) rows excluded.</div><div id="calibration"></div></section>
      </div>
    </div>

    <div id="compare" class="page">
      <div class="grid">
        <section class="panel wide"><h2>Demo/local vs production comparison</h2><div class="hint">Matched by ticker. This answers whether a local or demo-looking edge was actually fillable on live production books.</div><div id="shadowCompare"></div></section>
        <section class="panel wide"><h2>Recent local signals</h2><div id="signals"></div></section>
        <section class="panel wide"><h2>Demo orders</h2><div id="demoOrders"></div></section>
      </div>
    </div>

    <div id="events" class="page">
      <div class="grid">
        <section class="panel wide"><h2>Runner events</h2><div id="runnerEvents"></div></section>
        <section class="panel wide"><h2>Raw counts</h2><div id="rawCounts"></div></section>
      </div>
    </div>
  </main>
</div>
<script>
const pages = [
  ['home','Home','A quick read on whether the strategy is seeing live, executable weather edges.'],
  ['scans','Scan information','Coverage, skip reasons, and whether the scanner is seeing enough liquid markets.'],
  ['open','Open bids','Current shadow fills, local paper exposure, and live quote snapshots.'],
  ['settled','Settled contracts','Closed outcomes, win rate, realized shadow P/L, and side-level performance.'],
  ['compare','Live comparison','Local and demo-looking signals matched against production fillability.'],
  ['events','System log','Runner events and low-level database counts.']
];
let DATA = null;
const $ = id => document.getElementById(id);
const cents = v => v === null || v === undefined ? '—' : Number(v).toFixed(2) + '¢';
const signedCents = v => v === null || v === undefined ? '—' : `${Number(v) >= 0 ? '+' : ''}${Number(v).toFixed(2)}¢`;
const pct = v => v === null || v === undefined ? '—' : (Number(v) * 100).toFixed(1) + '%';
const clsPnL = v => Number(v || 0) >= 0 ? 'good' : 'bad';
function initNav() {
  $('nav').innerHTML = pages.map(([id,label]) => `<button data-page="${id}" onclick="showPage('${id}')">${label}</button>`).join('');
}
function showPage(id) {
  for (const el of document.querySelectorAll('.page')) el.classList.toggle('active', el.id === id);
  for (const el of document.querySelectorAll('nav button')) el.classList.toggle('active', el.dataset.page === id);
  const page = pages.find(p => p[0] === id) || pages[0];
  $('pageTitle').textContent = page[1];
  $('pageLede').textContent = page[2];
  location.hash = id;
}
function table(rows, cols, empty='No rows yet.') {
  if (!rows || rows.length === 0) return `<p class="empty">${empty}</p>`;
  return `<table><thead><tr>${cols.map(c=>`<th class="${c.num?'num':''}">${c.label}</th>`).join('')}</tr></thead><tbody>` +
    rows.map(r=>`<tr>${cols.map(c=>`<td class="${c.num?'num':''}">${c.render ? c.render(r) : (r[c.key] ?? '—')}</td>`).join('')}</tr>`).join('') + `</tbody></table>`;
}
function lineChart(rows, xKey, yKey, cls='') {
  if (!rows || rows.length === 0) return '<p class="empty">No chart data yet.</p>';
  const w=760,h=210,p=28;
  const ys = rows.map(r=>Number(r[yKey] || 0));
  const min = Math.min(0, ...ys), max = Math.max(1, ...ys), span = Math.max(1, max - min);
  const step = rows.length === 1 ? 0 : (w-p*2)/(rows.length-1);
  const pts = rows.map((r,i)=>[p+i*step, h-p-((Number(r[yKey]||0)-min)/span)*(h-p*2)]);
  const zeroY = h-p-((0-min)/span)*(h-p*2);
  const d = pts.map((pt,i)=>`${i?'L':'M'}${pt[0].toFixed(1)},${pt[1].toFixed(1)}`).join(' ');
  return `<svg viewBox="0 0 ${w} ${h}"><line class="axis" x1="${p}" y1="${zeroY}" x2="${w-p}" y2="${zeroY}"/><line class="axis" x1="${p}" y1="${p}" x2="${p}" y2="${h-p}"/><path class="line ${cls}" d="${d}"/><text class="chart-label" x="${p}" y="${h-5}">${rows[0][xKey] || ''}</text><text class="chart-label" x="${w-p-80}" y="${h-5}">${rows[rows.length-1][xKey] || ''}</text></svg>`;
}
function multiBar(rows, keys) {
  if (!rows || rows.length === 0) return '<p class="empty">No chart data yet.</p>';
  const w=900,h=220,p=30,g=10;
  const max = Math.max(1, ...rows.flatMap(r => keys.map(k => Number(r[k.key] || 0))));
  const groupW = (w-p*2-g*(rows.length-1))/rows.length;
  const bw = Math.max(5, groupW/keys.length - 2);
  let out = `<svg viewBox="0 0 ${w} ${h}"><line class="axis" x1="${p}" y1="${h-p}" x2="${w-p}" y2="${h-p}"/>`;
  rows.forEach((r,i)=>{
    keys.forEach((k,j)=>{
      const val = Number(r[k.key] || 0), bh = (val/max)*(h-p*2), x=p+i*(groupW+g)+j*(bw+2), y=h-p-bh;
      out += `<rect class="bar ${k.cls||''}" x="${x}" y="${y}" width="${bw}" height="${bh}" rx="4"><title>${k.label}: ${val}</title></rect>`;
    });
    if (i === 0 || i === rows.length-1 || rows.length < 8) out += `<text class="chart-label" x="${p+i*(groupW+g)}" y="${h-5}">${String(r.bucket||'').slice(0,11)}</text>`;
  });
  return out + `</svg>`;
}
function barChart(rows, labelKey, valueKey) {
  if (!rows || rows.length === 0) return '<p class="empty">No chart data yet.</p>';
  const w=640,h=210,p=30;
  const max = Math.max(1, ...rows.map(r=>Number(r[valueKey] || 0)));
  const bw = Math.max(18, (w-p*2)/rows.length - 8);
  let out = `<svg viewBox="0 0 ${w} ${h}"><line class="axis" x1="${p}" y1="${h-p}" x2="${w-p}" y2="${h-p}"/>`;
  rows.forEach((r,i)=>{
    const val=Number(r[valueKey]||0), bh=(val/max)*(h-p*2), x=p+i*(bw+8), y=h-p-bh;
    const label=String(r[labelKey] || 'none').replace('production_','').replace('insufficient_fee_adjusted_edge','low edge').replace('no_executable_production_liquidity','no liquidity').replace('no_executable_liquidity','no liquidity');
    out += `<rect class="bar ${i===0?'amber':''}" x="${x}" y="${y}" width="${bw}" height="${bh}" rx="6"/><text class="chart-label" x="${x}" y="${Math.max(13,y-5)}">${val}</text><text class="chart-label" x="${x}" y="${h-5}">${label.slice(0,13)}</text>`;
  });
  return out + `</svg>`;
}
async function refresh() {
  $('status').textContent = 'Loading data...';
  const res = await fetch('/api/summary');
  DATA = await res.json();
  render(DATA);
  $('status').textContent = 'Updated ' + new Date().toLocaleTimeString();
}
function render(data) {
  $('metrics').innerHTML = [
    ['Shadow fills', data.counts.shadow_orders], ['Shadow P/L', `<span class="${clsPnL(data.shadow_pnl.realized_pnl_cents)}">${signedCents(data.shadow_pnl.realized_pnl_cents)}</span>`], ['Shadow win', pct(data.shadow_pnl.win_rate)], ['Paper wins', data.pnl.winning_orders || 0], ['Paper P/L', `<span class="${clsPnL(data.pnl.realized_pnl_cents)}">${signedCents(data.pnl.realized_pnl_cents)}</span>`], ['Live snapshots', data.counts.shadow_snapshots]
  ].map(([k,v])=>`<div class="metric"><b>${v}</b><span>${k}</span></div>`).join('');
  $('runChart').innerHTML = multiBar(data.scan_series, [{key:'signals',label:'Signals',cls:'blue'}, {key:'paper_orders',label:'Paper fills',cls:'amber'}, {key:'shadow_snapshots',label:'Shadow snapshots',cls:'green'}, {key:'shadow_orders',label:'Shadow fills',cls:'red'}]);
  $('fillabilityChart').innerHTML = barChart(data.shadow_fillability, 'label', 'count');
  $('shadowPnlChart').innerHTML = lineChart(data.shadow_pnl_series, 'bucket', 'realized_pnl_cents', Number(data.shadow_pnl.realized_pnl_cents || 0) >= 0 ? 'green' : 'red');
  $('latestStatus').innerHTML = table(data.runner_events.slice(0,5), [{label:'Time', key:'created_at'}, {label:'Level', key:'level'}, {label:'Message', key:'message'}], 'No runner events yet.');
  $('scanRuns').innerHTML = table(data.scan_runs, [{label:'Scan', key:'id', num:true}, {label:'Started', key:'started_at'}, {label:'Signals', key:'signals', num:true}, {label:'Paper fills', key:'paper_orders', num:true}, {label:'Shadow quotes', key:'shadow_snapshots', num:true}, {label:'Shadow fills', key:'shadow_orders', num:true}, {label:'Notes', key:'notes'}]);
  $('paperSkips').innerHTML = table(data.skip_reasons, [{label:'Reason', render:r=>`<span class="pill">${r.skipped_reason || 'filled candidate'}</span>`}, {label:'Count', key:'count', num:true}]);
  $('shadowSkips').innerHTML = table(data.shadow_skip_reasons, [{label:'Reason', render:r=>`<span class="pill">${r.skipped_reason || 'shadow filled'}</span>`}, {label:'Count', key:'count', num:true}]);
  $('sideChart').innerHTML = barChart(data.side_mix, 'selected_side', 'count');
  $('shadowSideChart').innerHTML = barChart(data.shadow_side_mix, 'selected_side', 'count');
  $('openShadow').innerHTML = orderTable(data.open_shadow_orders, 'No open shadow fills.');
  $('settledShadow').innerHTML = orderTable(data.settled_shadow_orders, 'No settled shadow fills yet.');
  $('positions').innerHTML = table(data.positions, [{label:'Ticker', render:r=>`<span class="ticker">${r.ticker}</span>`}, {label:'Side', key:'side'}, {label:'Qty', key:'quantity', num:true}, {label:'Avg', render:r=>cents(r.avg_price_cents), num:true}, {label:'Fees', render:r=>cents(r.total_fees_cents), num:true}], 'No open paper positions.');
  $('shadowSnapshots').innerHTML = snapshotTable(data.shadow_snapshots);
  $('shadowPnlBySide').innerHTML = table(data.shadow_pnl_by_side, [{label:'Side', key:'side'}, {label:'Orders', key:'orders', num:true}, {label:'Wins', key:'wins', num:true}, {label:'P/L', render:r=>`<span class="${clsPnL(r.realized_pnl_cents)}">${signedCents(r.realized_pnl_cents)}</span>`, num:true}], 'No settled shadow orders.');
  $('pnlBySide').innerHTML = table(data.pnl_by_side, [{label:'Side', key:'side'}, {label:'Orders', key:'orders', num:true}, {label:'Wins', key:'wins', num:true}, {label:'P/L', render:r=>signedCents(r.realized_pnl_cents), num:true}], 'No settled paper orders.');
  $('calibration').innerHTML = calibrationHtml(data.calibration);
  $('shadowCompare').innerHTML = table(data.shadow_comparison, [{label:'Ticker', render:r=>`<span class="ticker">${r.ticker}</span>`}, {label:'Local side', key:'local_side'}, {label:'Prod side', key:'production_side'}, {label:'Local', render:r=>cents(r.local_price_cents), num:true}, {label:'Prod', render:r=>cents(r.production_price_cents), num:true}, {label:'Diff', render:r=>signedCents(r.price_diff_cents), num:true}, {label:'Prod size', key:'production_size', num:true}, {label:'Fillable', render:r=>r.production_fillable ? '<span class="good">yes</span>' : '<span class="bad">no</span>'}, {label:'Prod skip', key:'production_skip'}], 'No overlapping local and production tickers yet.');
  $('signals').innerHTML = table(data.recent_signals, [{label:'Ticker', render:r=>`<span class="ticker">${r.ticker}</span>`}, {label:'Side', key:'selected_side'}, {label:'City', key:'city'}, {label:'P(YES)', render:r=>pct(r.probability_yes), num:true}, {label:'YES ask', render:r=>cents(r.yes_ask_cents), num:true}, {label:'NO ask', render:r=>cents(r.no_ask_cents), num:true}, {label:'Selected', render:r=>cents(r.selected_price_cents), num:true}, {label:'EV', render:r=>cents(r.fee_adjusted_ev_cents), num:true}, {label:'Skip', key:'skipped_reason'}]);
  $('demoOrders').innerHTML = table(data.demo_orders, [{label:'Ticker', render:r=>`<span class="ticker">${r.ticker}</span>`}, {label:'Side', key:'side'}, {label:'Client order', key:'client_order_id'}, {label:'Price', key:'price_dollars', num:true}, {label:'Qty', key:'quantity', num:true}, {label:'Status', key:'status'}, {label:'Error', key:'error'}], 'No demo orders.');
  $('runnerEvents').innerHTML = table(data.runner_events, [{label:'Time', key:'created_at'}, {label:'Level', key:'level'}, {label:'Message', key:'message'}], 'No runner events.');
  $('rawCounts').innerHTML = table(Object.entries(data.counts).map(([name,count])=>({name,count})), [{label:'Table', key:'name'}, {label:'Rows', key:'count', num:true}]);
}
function calibrationHtml(c) {
  if (!c) return '<div class="hint">No calibration data yet.</div>';
  function block(name, r) {
    if (!r || !r.n) return `<div class="metric"><b>—</b><span>${name}: no settled outcomes</span></div>`;
    const fc = (r.forecast_mae != null) ? ` <div class="metric"><b>${r.forecast_mae.toFixed(2)}°</b><span>${name} forecast MAE (bias ${r.forecast_bias>=0?'+':''}${r.forecast_bias.toFixed(2)})</span></div>` : '';
    return `<div class="metric"><b>${r.brier.toFixed(3)}</b><span>${name} Brier (0.25=coin)</span></div>`
      + `<div class="metric"><b>${(r.mean_predicted*100).toFixed(0)}% / ${(r.win_rate*100).toFixed(0)}%</b><span>${name} predicted / actual</span></div>`
      + `<div class="metric"><b>${r.n_events}</b><span>${name} independent events (n=${r.n})</span></div>`
      + fc;
  }
  return `<div class="metrics">${block('Paper', c.paper)}${block('Shadow', c.shadow)}</div>`;
}
function orderTable(rows, empty) {
  return table(rows, [{label:'Ticker', render:r=>`<span class="ticker">${r.ticker}</span>`}, {label:'Side', key:'side'}, {label:'Qty', key:'quantity', num:true}, {label:'Fill', render:r=>cents(r.avg_fill_price_cents), num:true}, {label:'Fee', render:r=>cents(r.fee_cents), num:true}, {label:'Result', key:'settlement_result'}, {label:'P/L', render:r=>`<span class="${clsPnL(r.realized_pnl_cents)}">${signedCents(r.realized_pnl_cents)}</span>`, num:true}, {label:'Status', key:'status'}, {label:'Time', key:'created_at'}], empty);
}
function snapshotTable(rows) {
  return table(rows, [{label:'Ticker', render:r=>`<span class="ticker">${r.ticker}</span>`}, {label:'Side', key:'selected_side'}, {label:'City', key:'city'}, {label:'YES ask', render:r=>cents(r.yes_ask_cents), num:true}, {label:'YES size', key:'yes_ask_size', num:true}, {label:'NO ask', render:r=>cents(r.no_ask_cents), num:true}, {label:'NO size', key:'no_ask_size', num:true}, {label:'Spread', render:r=>cents(r.spread_cents), num:true}, {label:'EV', render:r=>cents(r.fee_adjusted_ev_cents), num:true}, {label:'Skip', key:'skipped_reason'}], 'No production snapshots yet.');
}
async function runPaper() {
  $('status').textContent = 'Running paper scan...';
  const res = await fetch('/api/run-paper?limit=' + encodeURIComponent($('limit').value || 50), { method: 'POST' });
  const data = await res.json();
  if (!res.ok) { $('status').textContent = data.error || 'Run failed'; return; }
  $('status').textContent = `Paper scan ${data.scan_id}: ${data.orders_filled} fills`;
  await refresh();
}
async function runShadow() {
  $('status').textContent = 'Running production shadow scan...';
  const res = await fetch('/api/run-shadow?limit=' + encodeURIComponent($('limit').value || 50), { method: 'POST' });
  const data = await res.json();
  if (!res.ok) { $('status').textContent = data.error || 'Shadow scan failed'; return; }
  $('status').textContent = `Shadow scan ${data.scan_id}: ${data.shadow_orders_filled} fills`;
  await refresh();
}
initNav();
showPage((location.hash || '#home').slice(1));
refresh();
</script>
</body>
</html>
"""


class DashboardHandler(BaseHTTPRequestHandler):
    db_path = DEFAULT_DB

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send_html(HTML)
        elif parsed.path == "/api/summary":
            self._send_json(load_summary(self.db_path))
        else:
            self.send_error(404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        limit_arg = query.get("limit", [None])[0]
        try:
            load_dotenv(".env")
            settings = Settings()
            limit = int(limit_arg) if limit_arg else settings.kalshi_market_limit
            store = Store(self.db_path)
            if parsed.path == "/api/run-paper":
                result = PaperTrader(settings, store).run_once(limit)
                self._send_json(result.__dict__)
                return
            if parsed.path == "/api/run-shadow":
                tracker = ProductionShadowTracker(settings, store, fee_model=FeeModel())
                result = tracker.run_once(limit)
                settled = tracker.reconcile_settlements()
                payload = {**result.__dict__, "shadow_settlement_markets_checked": settled.markets_checked, "shadow_orders_settled": settled.orders_settled}
                self._send_json(payload)
                return
            self.send_error(404)
        except Exception as exc:  # noqa: BLE001
            self._send_json({"error": str(exc)}, status=500)

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        return

    def _send_html(self, body: str) -> None:
        payload = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_json(self, body: object, status: int = 200) -> None:
        payload = json.dumps(body, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def rows(conn: object, sql: str, params: tuple = ()) -> list[dict]:
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def one(conn: object, sql: str, params: tuple = ()) -> dict | None:
    row = conn.execute(sql, params).fetchone()
    return dict(row) if row else None


def _count(conn: object, table: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def load_summary(db_path: str) -> dict:
    # Local SQLite that has never been written to: report an empty dashboard rather than
    # creating a stray file. (Postgres always connects.)
    if not _is_postgres_target(db_path) and not Path(db_path).exists():
        return _empty_summary()
    store = Store(db_path)
    conn = store.conn
    # Hour-bucket label expression differs by backend (SQLite strftime vs Postgres to_char).
    if store.is_postgres:
        def bucket(col: str) -> str:
            return f"to_char({col}, 'MM-DD HH24\":00\"')"
    else:
        def bucket(col: str) -> str:
            return f"strftime('%m-%d %H:00', {col})"
    try:
        pnl = one(conn, """
            SELECT
              COALESCE(SUM(realized_pnl_cents), 0) AS realized_pnl_cents,
              COUNT(realized_pnl_cents) AS settled_orders,
              SUM(CASE WHEN realized_pnl_cents > 0 THEN 1 ELSE 0 END) AS winning_orders,
              COALESCE(SUM(CASE WHEN status = 'FILLED' AND realized_pnl_cents IS NULL THEN quantity * avg_fill_price_cents ELSE 0 END), 0) AS open_exposure_cents
            FROM paper_orders
        """) or {}
        pnl["win_rate"] = _win_rate(pnl)
        shadow_pnl = one(conn, """
            SELECT
              COALESCE(SUM(realized_pnl_cents), 0) AS realized_pnl_cents,
              COUNT(realized_pnl_cents) AS settled_orders,
              SUM(CASE WHEN realized_pnl_cents > 0 THEN 1 ELSE 0 END) AS winning_orders,
              COALESCE(SUM(CASE WHEN status = 'SHADOW_FILLED' AND realized_pnl_cents IS NULL THEN quantity * avg_fill_price_cents ELSE 0 END), 0) AS open_exposure_cents
            FROM shadow_orders
        """) or {}
        shadow_pnl["win_rate"] = _win_rate(shadow_pnl)
        return {
            "counts": {
                "scans": _count(conn, "scans"),
                "signals": _count(conn, "signals"),
                "orders": _count(conn, "paper_orders"),
                "positions": conn.execute("SELECT COUNT(*) FROM (SELECT 1 FROM paper_orders WHERE status = 'FILLED' AND realized_pnl_cents IS NULL GROUP BY ticker, side) AS sub").fetchone()[0],
                "demo_orders": _count(conn, "demo_orders"),
                "shadow_snapshots": _count(conn, "shadow_snapshots"),
                "shadow_orders": _count(conn, "shadow_orders"),
                "runner_events": _count(conn, "runner_events"),
            },
            "pnl": pnl,
            "shadow_pnl": shadow_pnl,
            "latest_scan": one(conn, "SELECT * FROM scans ORDER BY id DESC LIMIT 1"),
            "scan_runs": rows(conn, """
                SELECT s.id, s.started_at, s.market_limit, s.notes,
                       COUNT(DISTINCT sig.id) AS signals,
                       COUNT(DISTINCT po.id) AS paper_orders,
                       COUNT(DISTINCT sh.id) AS shadow_snapshots,
                       COUNT(DISTINCT so.id) AS shadow_orders
                FROM scans s
                LEFT JOIN signals sig ON sig.scan_id = s.id
                LEFT JOIN paper_orders po ON po.scan_id = s.id
                LEFT JOIN shadow_snapshots sh ON sh.scan_id = s.id
                LEFT JOIN shadow_orders so ON so.scan_id = s.id
                GROUP BY s.id
                ORDER BY s.id DESC
                LIMIT 40
            """),
            "scan_series": rows(conn, f"""
                SELECT {bucket('s.started_at')} AS bucket,
                       COUNT(DISTINCT sig.id) AS signals,
                       COUNT(DISTINCT po.id) AS paper_orders,
                       COUNT(DISTINCT sh.id) AS shadow_snapshots,
                       COUNT(DISTINCT so.id) AS shadow_orders
                FROM scans s
                LEFT JOIN signals sig ON sig.scan_id = s.id
                LEFT JOIN paper_orders po ON po.scan_id = s.id
                LEFT JOIN shadow_snapshots sh ON sh.scan_id = s.id
                LEFT JOIN shadow_orders so ON so.scan_id = s.id
                GROUP BY bucket
                ORDER BY MIN(s.started_at)
                LIMIT 48
            """),
            "skip_reasons": rows(conn, "SELECT skipped_reason, COUNT(*) AS count FROM signals GROUP BY skipped_reason ORDER BY count DESC"),
            "shadow_skip_reasons": rows(conn, "SELECT skipped_reason, COUNT(*) AS count FROM shadow_snapshots GROUP BY skipped_reason ORDER BY count DESC"),
            "shadow_fillability": rows(conn, """
                SELECT CASE WHEN skipped_reason IS NULL THEN 'fillable' ELSE 'skipped' END AS label, COUNT(*) AS count
                FROM shadow_snapshots
                GROUP BY label
                ORDER BY count DESC
            """),
            "side_mix": rows(conn, "SELECT COALESCE(selected_side, 'UNKNOWN') AS selected_side, COUNT(*) AS count FROM signals GROUP BY selected_side ORDER BY count DESC"),
            "shadow_side_mix": rows(conn, "SELECT COALESCE(selected_side, 'UNKNOWN') AS selected_side, COUNT(*) AS count FROM shadow_snapshots GROUP BY selected_side ORDER BY count DESC"),
            "recent_signals": rows(conn, "SELECT * FROM signals ORDER BY id DESC LIMIT 40"),
            "demo_orders": rows(conn, "SELECT * FROM demo_orders ORDER BY id DESC LIMIT 40"),
            "positions": rows(conn, "SELECT ticker, side, SUM(quantity) AS quantity, AVG(avg_fill_price_cents) AS avg_price_cents, SUM(COALESCE(fee_cents,0)) AS total_fees_cents, MAX(created_at) AS updated_at FROM paper_orders WHERE status = 'FILLED' AND realized_pnl_cents IS NULL GROUP BY ticker, side ORDER BY updated_at DESC LIMIT 80"),
            "open_shadow_orders": rows(conn, "SELECT * FROM shadow_orders WHERE status = 'SHADOW_FILLED' AND realized_pnl_cents IS NULL ORDER BY id DESC LIMIT 80"),
            "settled_shadow_orders": rows(conn, "SELECT * FROM shadow_orders WHERE realized_pnl_cents IS NOT NULL ORDER BY COALESCE(settled_at, created_at) DESC LIMIT 80"),
            "shadow_snapshots": rows(conn, "SELECT * FROM shadow_snapshots ORDER BY id DESC LIMIT 80"),
            "runner_events": rows(conn, "SELECT * FROM runner_events ORDER BY id DESC LIMIT 80"),
            "pnl_by_side": rows(conn, "SELECT side, COUNT(*) AS orders, SUM(CASE WHEN realized_pnl_cents > 0 THEN 1 ELSE 0 END) AS wins, COALESCE(SUM(realized_pnl_cents), 0) AS realized_pnl_cents FROM paper_orders WHERE realized_pnl_cents IS NOT NULL GROUP BY side ORDER BY side"),
            "shadow_pnl_by_side": rows(conn, "SELECT side, COUNT(*) AS orders, SUM(CASE WHEN realized_pnl_cents > 0 THEN 1 ELSE 0 END) AS wins, COALESCE(SUM(realized_pnl_cents), 0) AS realized_pnl_cents FROM shadow_orders WHERE realized_pnl_cents IS NOT NULL GROUP BY side ORDER BY side"),
            "shadow_pnl_series": rows(conn, f"SELECT {bucket('COALESCE(settled_at, created_at)')} AS bucket, COALESCE(SUM(realized_pnl_cents), 0) AS realized_pnl_cents FROM shadow_orders WHERE realized_pnl_cents IS NOT NULL GROUP BY bucket ORDER BY MIN(COALESCE(settled_at, created_at)) LIMIT 48"),
            "shadow_comparison": rows(conn, """
                WITH latest_signal AS (
                  SELECT s1.* FROM signals s1
                  JOIN (SELECT ticker, MAX(id) AS id FROM signals GROUP BY ticker) x ON x.id = s1.id
                )
                SELECT
                  sh.ticker,
                  ls.selected_side AS local_side,
                  sh.selected_side AS production_side,
                  ls.selected_price_cents AS local_price_cents,
                  sh.selected_price_cents AS production_price_cents,
                  sh.selected_price_cents - ls.selected_price_cents AS price_diff_cents,
                  CASE WHEN sh.selected_side = 'BUY_YES' THEN sh.yes_ask_size ELSE sh.no_ask_size END AS production_size,
                  CASE WHEN sh.skipped_reason IS NULL THEN 1 ELSE 0 END AS production_fillable,
                  sh.skipped_reason AS production_skip
                FROM shadow_snapshots sh
                JOIN latest_signal ls ON ls.ticker = sh.ticker
                ORDER BY sh.id DESC
                LIMIT 80
            """),
            "calibration": _calibration_summary(store),
        }
    finally:
        conn.close()


def _calibration_summary(store: Store) -> dict:
    """Headline calibration metrics for the dashboard (leakage-flagged rows excluded)."""
    out = {}
    for source in ("paper", "shadow"):
        r = compute_calibration(store, source=source, include_lookahead=False)
        out[source] = {
            "n": r.n,
            "n_events": r.n_events,
            "brier": r.brier,
            "mean_predicted": r.mean_predicted,
            "win_rate": r.win_rate,
            "forecast_mae": r.forecast_mae,
            "forecast_bias": r.forecast_bias,
        }
    return out


def _win_rate(summary: dict) -> float | None:
    settled = int(summary.get("settled_orders") or 0)
    wins = int(summary.get("winning_orders") or 0)
    return (wins / settled) if settled else None


def _empty_summary() -> dict:
    return {
        "counts": {"scans": 0, "signals": 0, "orders": 0, "positions": 0, "demo_orders": 0, "shadow_snapshots": 0, "shadow_orders": 0, "runner_events": 0},
        "pnl": {"realized_pnl_cents": 0, "open_exposure_cents": 0, "settled_orders": 0, "winning_orders": 0, "win_rate": None},
        "shadow_pnl": {"realized_pnl_cents": 0, "open_exposure_cents": 0, "settled_orders": 0, "winning_orders": 0, "win_rate": None},
        "latest_scan": None,
        "scan_runs": [], "scan_series": [], "skip_reasons": [], "shadow_skip_reasons": [], "shadow_fillability": [],
        "side_mix": [], "shadow_side_mix": [], "recent_signals": [], "demo_orders": [], "positions": [], "open_shadow_orders": [],
        "settled_shadow_orders": [], "shadow_snapshots": [], "runner_events": [], "pnl_by_side": [], "shadow_pnl_by_side": [],
        "shadow_pnl_series": [], "shadow_comparison": [],
        "calibration": {"paper": {}, "shadow": {}},
    }


def main(argv: list[str] | None = None) -> int:
    load_dotenv(".env")
    parser = argparse.ArgumentParser(description="Kalshi weather bot web dashboard")
    # Default to 0.0.0.0 / $PORT so the container is reachable on Railway; override locally if desired.
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8787")))
    parser.add_argument("--db", default=DEFAULT_DB)
    args = parser.parse_args(argv)

    # Hosted Postgres (DATABASE_URL) takes precedence over the local SQLite path.
    db_target = Settings().database_url or args.db
    DashboardHandler.db_path = db_target
    server = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    shown_db = "postgres" if _is_postgres_target(db_target) else db_target
    print(f"Dashboard running at http://{args.host}:{args.port}")
    print(f"Using database: {shown_db}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
