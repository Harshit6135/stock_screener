"""Interactive browser shell for research, pipeline, backtest, actions, portfolio, and configs."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from flask import Blueprint, Response

NAV_LINKS = """
<div class="navbar">
  <div class="nav-links">
    <span style="font-weight:700;font-size:1.1rem;margin-right:0.5rem;color:#60a5fa;">StockScreener</span>
    <a href="/app" class="__ACTIVE_APP__">Overview</a>
    <a href="/dashboard" class="__ACTIVE_DASHBOARD__">Dashboard</a>
    <a href="/pipeline" class="__ACTIVE_PIPELINE__">Pipeline</a>
    <a href="/backtest" class="__ACTIVE_BACKTEST__">Backtest</a>
    <a href="/actions" class="__ACTIVE_ACTIONS__">Actions</a>
    <a href="/portfolio" class="__ACTIVE_PORTFOLIO__">Portfolio</a>
    <a href="/configs" class="__ACTIVE_CONFIGS__">Configs</a>
    <a href="/integrations/kite" class="__ACTIVE_KITE__">Kite Auth</a>
  </div>
  <div class="token-bar">
    <label for="op-token">Operator Token:</label>
    <input id="op-token" type="password" placeholder="SCREENER_OPERATOR_TOKEN" class="token-input" autocomplete="off">
  </div>
</div>
"""

BASE_STYLE = """
<style>
:root {
  --bg: #0f172a; --card: #1e293b; --card-border: #334155; --text: #f8fafc;
  --text-muted: #94a3b8; --primary: #3b82f6; --primary-hover: #2563eb;
  --success: #10b981; --warning: #f59e0b; --danger: #ef4444;
}
* { box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 0 1.5rem 3rem; }
.navbar { display: flex; flex-wrap: wrap; gap: 0.5rem; padding: 1rem 0; border-bottom: 1px solid #334155; margin-bottom: 1.5rem; align-items: center; justify-content: space-between; }
.nav-links { display: flex; flex-wrap: wrap; gap: 0.5rem; align-items: center; }
.nav-links a { color: #94a3b8; text-decoration: none; padding: 0.4rem 0.8rem; border-radius: 6px; font-size: 0.9rem; font-weight: 500; transition: all 0.15s; }
.nav-links a:hover, .nav-links a.active { color: #fff; background: #334155; }
.nav-links a.active { background: #2563eb; }
.token-bar { display: flex; align-items: center; gap: 0.5rem; font-size: 0.85rem; color: #94a3b8; }
.token-input { background: #1e293b; border: 1px solid #475569; color: #fff; border-radius: 4px; padding: 0.3rem 0.5rem; font-size: 0.85rem; width: 170px; }
.card { background: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 1.25rem; margin-bottom: 1.5rem; }
.card-header { font-size: 1.1rem; font-weight: 600; margin-bottom: 1rem; display: flex; justify-content: space-between; align-items: center; }
.grid-2 { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 1rem; }
.grid-3 { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; }
.grid-4 { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 1rem; }
.form-row { display: flex; flex-wrap: wrap; gap: 1rem; align-items: center; margin-bottom: 0.75rem; }
.form-group { display: flex; flex-direction: column; gap: 0.35rem; font-size: 0.85rem; color: #94a3b8; }
.stat-card { background: #0f172a; border: 1px solid #334155; border-radius: 6px; padding: 0.85rem; }
.stat-label { font-size: 0.75rem; text-transform: uppercase; color: #94a3b8; letter-spacing: 0.05em; }
.stat-value { font-size: 1.35rem; font-weight: 700; margin-top: 0.25rem; color: #fff; }
table { width: 100%; border-collapse: collapse; font-size: 0.9rem; margin-top: 0.5rem; }
th, td { text-align: left; padding: 0.6rem 0.75rem; border-bottom: 1px solid #334155; }
th { color: #94a3b8; font-weight: 600; background: #182234; }
tr:hover td { background: rgba(255,255,255,0.02); }
input, select, button { font: inherit; background: #0f172a; border: 1px solid #475569; color: #fff; border-radius: 6px; padding: 0.45rem 0.75rem; }
input[type="checkbox"] { width: 1.1rem; height: 1.1rem; cursor: pointer; }
button { background: #2563eb; border-color: #3b82f6; cursor: pointer; font-weight: 500; transition: background 0.15s; }
button:hover { background: #1d4ed8; }
button.secondary { background: #334155; border-color: #475569; }
button.secondary:hover { background: #475569; }
button.danger { background: #dc2626; border-color: #ef4444; }
button.danger:hover { background: #b91c1c; }
button.success { background: #059669; border-color: #10b981; }
button.success:hover { background: #047857; }
button.small { padding: 0.25rem 0.5rem; font-size: 0.8rem; }
.badge { display: inline-block; padding: 0.2rem 0.5rem; border-radius: 4px; font-size: 0.75rem; font-weight: 600; text-transform: uppercase; }
.badge-green { background: #064e3b; color: #6ee7b7; }
.badge-blue { background: #1e3a8a; color: #93c5fd; }
.badge-amber { background: #78350f; color: #fcd34d; }
.badge-red { background: #7f1d1d; color: #fca5a5; }
.badge-gray { background: #334155; color: #cbd5e1; }
.muted { color: #94a3b8; }
.positive { color: #34d399; font-weight: 600; }
.negative { color: #f87171; font-weight: 600; }
pre { background: #0f172a; border: 1px solid #334155; border-radius: 6px; padding: 1rem; overflow: auto; font-size: 0.85rem; max-height: 400px; color: #93c5fd; }
progress { width: 100%; height: 1.1rem; border-radius: 6px; }
</style>
<script>
function getToken() {
  let t = document.getElementById('op-token')?.value;
  if (!t) t = localStorage.getItem('operator_token') || '';
  if (!t) {
    t = prompt('Local operator token:') || '';
    if (t) { localStorage.setItem('operator_token', t); const el = document.getElementById('op-token'); if (el) el.value = t; }
  }
  return t;
}
function saveToken(v) { localStorage.setItem('operator_token', v); }
window.addEventListener('DOMContentLoaded', () => {
  const el = document.getElementById('op-token');
  if (el) {
    el.value = localStorage.getItem('operator_token') || '';
    el.addEventListener('input', (e) => saveToken(e.target.value));
  }
});
</script>
"""

def _render_nav(active_page: str) -> str:
    nav = NAV_LINKS
    for key in ("APP", "DASHBOARD", "PIPELINE", "BACKTEST", "ACTIONS", "PORTFOLIO", "CONFIGS", "KITE"):
        nav = nav.replace(f"__{key}__", "active" if key.lower() == active_page.lower() else "")
    return nav


def create_dashboard_blueprint() -> Blueprint:
    blueprint = Blueprint("dashboard_v2", __name__)

    @blueprint.get("/app")
    def dashboard() -> Response:
        today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
        last_friday = today - timedelta(days=(today.weekday() - 4) % 7)
        if last_friday >= today:
            last_friday -= timedelta(days=7)
        page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Overview — Stock Screener</title>{BASE_STYLE}</head><body>
{_render_nav("app")}
<h1>Research & Operations Overview</h1>
<p class="muted">Research ranking view, index quotes, and job inspection. Live execution is disabled by default.</p>

<div class="grid-2">
  <div class="card">
    <div class="card-header">Weekly rankings</div>
    <div class="form-row">
      <div class="form-group"><label>Week Ending</label><input id="week" type="date" value="{last_friday.isoformat()}"></div>
      <div class="form-group"><label>Strategy</label><select id="strategy"><option value="strategy1">Strategy 1</option><option value="strategy2">Strategy 2 (provisional)</option></select></div>
      <div class="form-group" style="justify-content:flex-end;"><button id="load-rankings">Load Rankings</button></div>
    </div>
    <p id="ranking-status" role="status" class="muted"></p>
    <table><thead><tr><th>Rank</th><th>Symbol</th><th>Score</th></tr></thead><tbody id="rankings"></tbody></table>
  </div>

  <div class="card">
    <div class="card-header">Index quotes</div>
    <p class="muted" style="font-size:0.85rem;">Cached index quotes. Refresh jobs keep values current.</p>
    <div class="form-row"><button id="load-quotes">Refresh Quotes</button></div>
    <p id="quote-status" role="status" class="muted"></p>
    <table><thead><tr><th>Index</th><th>Last Price</th><th>Change %</th><th>Freshness</th></tr></thead><tbody id="quotes"></tbody></table>
  </div>
</div>

<div class="grid-2">
  <div class="card">
    <div class="card-header">Job Inspection</div>
    <div class="form-row">
      <div class="form-group"><label>Job ID</label><input id="job-id" type="number" min="1" placeholder="e.g. 1"></div>
      <div class="form-group" style="justify-content:flex-end;"><button id="load-job">Inspect</button></div>
    </div>
    <pre id="job-result">Enter a job ID to inspect state and progress.</pre>
  </div>

  <div class="card">
    <div class="card-header">Background Worker Control</div>
    <p class="muted" style="font-size:0.85rem;">Single-writer local worker processes queued background jobs.</p>
    <div class="form-row">
      <button id="worker-status-btn" class="secondary">Status</button>
      <button id="worker-start-btn" class="success">Start Worker</button>
      <button id="worker-stop-btn" class="danger">Stop Worker</button>
      <button id="worker-step-btn">Work Once</button>
    </div>
    <pre id="worker-result">Worker status will appear here.</pre>
  </div>
</div>

<div class="grid-2">
  <div class="card">
    <div class="card-header">Paper account</div>
    <div class="form-row">
      <div class="form-group"><label>Account ID</label><input id="account-id" value="paper" placeholder="e.g. paper"></div>
      <div class="form-group" style="justify-content:flex-end;"><button id="load-account">Look up</button></div>
    </div>
    <pre id="account-result">Look up paper account balance and valuation.</pre>
  </div>

  <div class="card">
    <div class="card-header">Paper action proposals</div>
    <p class="muted" style="font-size:0.85rem;">Review and process paper proposals. See full management in <a href="/actions" style="color:#60a5fa;">Actions</a>.</p>
    <div class="form-row">
      <div class="form-group"><label>Account ID</label><input id="action-account-id" value="paper"></div>
      <div class="form-group" style="justify-content:flex-end;"><button id="load-actions">Load proposals</button></div>
    </div>
    <p id="action-status" role="status" class="muted"></p>
    <table><thead><tr><th>Date</th><th>Strategy</th><th>Status</th><th>Decisions</th></tr></thead><tbody id="actions"></tbody></table>
  </div>
</div>

<script>
function cell(row, value, cls) {{
  const td = document.createElement('td');
  td.textContent = String(value);
  if (cls) td.className = cls;
  row.appendChild(td);
}}
async function loadRankings() {{
  const week = document.getElementById('week').value, strategy = document.getElementById('strategy').value;
  const status = document.getElementById('ranking-status'), body = document.getElementById('rankings');
  body.replaceChildren(); status.textContent = 'Loading rankings...';
  try {{
    const res = await fetch('/api/v2/research/rankings?week_end=' + encodeURIComponent(week) + '&strategy_id=' + strategy + '&limit=50');
    const data = await res.json();
    if (!res.ok) throw Error(data.error || 'Failed to load rankings');
    for (const item of data.members) {{
      const tr = document.createElement('tr');
      cell(tr, item.rank); cell(tr, item.symbol); cell(tr, Number(item.score).toFixed(2));
      body.appendChild(tr);
    }}
    status.textContent = data.members.length + ' rankings loaded.';
  }} catch (e) {{ status.textContent = e.message; }}
}}
async function loadQuotes() {{
  const status = document.getElementById('quote-status'), body = document.getElementById('quotes');
  body.replaceChildren(); status.textContent = 'Loading quotes...';
  try {{
    const res = await fetch('/api/v2/market/indices/quotes');
    const data = await res.json();
    if (!res.ok) throw Error(data.error || 'Failed to load quotes');
    for (const item of data.quotes) {{
      const tr = document.createElement('tr');
      cell(tr, item.exchange + ':' + item.symbol);
      cell(tr, item.last_price);
      const chg = Number(item.change_percent);
      cell(tr, (chg >= 0 ? '+' : '') + chg.toFixed(2) + '%', chg >= 0 ? 'positive' : 'negative');
      cell(tr, item.freshness);
      body.appendChild(tr);
    }}
    status.textContent = data.quotes.length + ' index quotes.';
  }} catch (e) {{ status.textContent = e.message; }}
}}
async function loadJob() {{
  const id = document.getElementById('job-id').value, out = document.getElementById('job-result');
  if (!id) return out.textContent = 'Enter a valid numeric job ID';
  try {{
    const res = await fetch('/api/v2/operations/jobs/' + encodeURIComponent(id));
    out.textContent = JSON.stringify(await res.json(), null, 2);
  }} catch (e) {{ out.textContent = e.message; }}
}}
async function checkWorker() {{
  const out = document.getElementById('worker-result');
  try {{
    const res = await fetch('/api/v2/operations/worker/status');
    out.textContent = JSON.stringify(await res.json(), null, 2);
  }} catch (e) {{ out.textContent = e.message; }}
}}
async function controlWorker(action) {{
  const out = document.getElementById('worker-result');
  const token = getToken();
  try {{
    const res = await fetch('/api/v2/operations/worker/' + action, {{
      method: 'POST',
      headers: {{ 'X-Operator-Token': token }}
    }});
    out.textContent = JSON.stringify(await res.json(), null, 2);
  }} catch (e) {{ out.textContent = e.message; }}
}}
document.getElementById('load-rankings').addEventListener('click', loadRankings);
document.getElementById('load-quotes').addEventListener('click', loadQuotes);
document.getElementById('load-job').addEventListener('click', loadJob);
document.getElementById('worker-status-btn').addEventListener('click', checkWorker);
document.getElementById('worker-start-btn').addEventListener('click', () => controlWorker('start'));
document.getElementById('worker-stop-btn').addEventListener('click', () => controlWorker('stop'));
document.getElementById('worker-step-btn').addEventListener('click', () => controlWorker('work-once'));
loadRankings(); loadQuotes(); checkWorker();
</script></body></html>"""
        return Response(page, mimetype="text/html")

    @blueprint.get("/actions")
    def actions_page() -> Response:
        today = datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
        page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Paper Actions — Stock Screener</title>{BASE_STYLE}</head><body>
{_render_nav("actions")}
<h1>Paper Action Proposals & Intents</h1>
<p class="muted">Review, approve, reject, or process paper rebalance proposals. Manual batch intents can also be generated.</p>

<div class="card">
  <div class="card-header">
    <span>Review Proposals</span>
    <div class="form-row" style="margin:0;">
      <input id="acc-id" value="paper" placeholder="Account ID" style="width:120px;">
      <button id="btn-load-proposals">Load Proposals</button>
    </div>
  </div>
  <p id="prop-status" class="muted"></p>
  <table>
    <thead><tr><th>ID</th><th>Date</th><th>Strategy</th><th>Status</th><th>Decisions</th><th>Actions</th></tr></thead>
    <tbody id="proposals-body"><tr><td colspan="6" class="muted">Click Load Proposals to view pending and approved proposals.</td></tr></tbody>
  </table>
</div>

<div id="proposal-detail-card" class="card" style="display:none;">
  <div class="card-header">
    <span id="detail-title">Proposal Details</span>
    <button class="secondary small" onclick="document.getElementById('proposal-detail-card').style.display='none'">Close</button>
  </div>
  <table>
    <thead><tr><th>Type</th><th>Symbol</th><th>Units</th><th>Price</th><th>Reason</th><th>Fee</th></tr></thead>
    <tbody id="detail-decisions"></tbody>
  </table>
</div>

<div class="card">
  <div class="card-header">Manual Intent Builder</div>
  <p class="muted" style="font-size:0.85rem;">Construct and dispatch manual paper entries without entering raw JSON.</p>
  <div class="form-row">
    <div class="form-group"><label>Account ID</label><input id="man-acc" value="paper" style="width:120px;"></div>
    <div class="form-group"><label>Action Date</label><input id="man-date" type="date" value="{today}"></div>
    <div class="form-group" style="flex:1;"><label>Reason</label><input id="man-reason" value="manual position adjustment" placeholder="Rationale"></div>
  </div>

  <table style="margin-bottom:1rem;">
    <thead><tr><th>Direction</th><th>Symbol</th><th>Units</th><th>Target Price</th><th>Action</th></tr></thead>
    <tbody id="intent-entries"></tbody>
  </table>
  <div class="form-row">
    <button id="add-entry-row" type="button" class="secondary">+ Add Entry</button>
    <button id="submit-manual-intent" type="button" class="success">Submit Manual Intent</button>
    <span id="intent-status" class="muted"></span>
  </div>
</div>

<script>
let proposalsData = [];
function badgeClass(status) {{
  if (status === 'PENDING') return 'badge-amber';
  if (status === 'APPROVED') return 'badge-blue';
  if (status === 'PROCESSED') return 'badge-green';
  if (status === 'REJECTED') return 'badge-red';
  return 'badge-gray';
}}

async function loadProposals() {{
  const acc = document.getElementById('acc-id').value;
  const statusEl = document.getElementById('prop-status');
  const tbody = document.getElementById('proposals-body');
  const token = getToken();
  statusEl.textContent = 'Loading proposals...';
  try {{
    const res = await fetch('/api/v2/actions/proposals?account_id=' + encodeURIComponent(acc), {{
      headers: {{ 'X-Operator-Token': token }}
    }});
    const data = await res.json();
    if (!res.ok) throw Error(data.error || 'Failed to load proposals');
    proposalsData = data.proposals || [];
    tbody.replaceChildren();
    if (proposalsData.length === 0) {{
      tbody.innerHTML = '<tr><td colspan="6" class="muted">No proposals found for ' + acc + '</td></tr>';
      statusEl.textContent = '0 proposals.';
      return;
    }}
    for (const p of proposalsData) {{
      const tr = document.createElement('tr');
      tr.innerHTML = '<td><code>' + p.proposal_id.slice(0, 8) + '...</code></td>' +
        '<td>' + p.action_date + '</td>' +
        '<td>' + p.strategy_id + '</td>' +
        '<td><span class="badge ' + badgeClass(p.status) + '">' + p.status + '</span></td>' +
        '<td>' + p.decisions.length + ' decisions</td>' +
        '<td><div style="display:flex;gap:0.35rem;">' +
        '<button class="secondary small" onclick="viewProposal(\\'' + p.proposal_id + '\\')">View</button>' +
        (p.status === 'PENDING' ? '<button class="success small" onclick="mutateProposal(\\'' + p.proposal_id + '\\', \\'approve\\')">Approve</button>' +
         '<button class="danger small" onclick="mutateProposal(\\'' + p.proposal_id + '\\', \\'reject\\')">Reject</button>' : '') +
        (p.status === 'APPROVED' ? '<button class="primary small" onclick="mutateProposal(\\'' + p.proposal_id + '\\', \\'process\\')">Process</button>' : '') +
        '</div></td>';
      tbody.appendChild(tr);
    }}
    statusEl.textContent = proposalsData.length + ' proposals loaded.';
  }} catch (e) {{ statusEl.textContent = e.message; }}
}}

function viewProposal(pid) {{
  const p = proposalsData.find(x => x.proposal_id === pid);
  if (!p) return;
  document.getElementById('proposal-detail-card').style.display = 'block';
  document.getElementById('detail-title').textContent = 'Proposal ' + pid + ' (' + p.status + ')';
  const tbody = document.getElementById('detail-decisions');
  tbody.replaceChildren();
  for (const d of p.decisions) {{
    const tr = document.createElement('tr');
    tr.innerHTML = '<td><b>' + d.type + '</b></td>' +
      '<td>' + (d.symbol || d.instrument_id) + '</td>' +
      '<td>' + (d.units?.units ?? d.units ?? '-') + '</td>' +
      '<td>' + (d.execution_price?.amount ?? d.price ?? '-') + '</td>' +
      '<td>' + (d.reason || '-') + '</td>' +
      '<td>' + (d.fee?.amount ?? '-') + '</td>';
    tbody.appendChild(tr);
  }}
}}

async function mutateProposal(pid, action) {{
  if (!confirm('Are you sure you want to ' + action + ' proposal ' + pid + '?')) return;
  const token = getToken();
  try {{
    const res = await fetch('/api/v2/actions/proposals/' + encodeURIComponent(pid) + '/' + action, {{
      method: 'POST',
      headers: {{ 'X-Operator-Token': token }}
    }});
    const data = await res.json();
    if (!res.ok) alert(data.error || 'Action failed');
    loadProposals();
  }} catch (e) {{ alert(e.message); }}
}}

function addIntentRow(type = 'BUY', symbol = '', units = 10, price = '100.0') {{
  const tbody = document.getElementById('intent-entries');
  const tr = document.createElement('tr');
  tr.innerHTML = '<td><select class="entry-type"><option value="BUY"' + (type === 'BUY' ? ' selected' : '') + '>BUY</option><option value="SELL"' + (type === 'SELL' ? ' selected' : '') + '>SELL</option></select></td>' +
    '<td><input class="entry-symbol" value="' + symbol + '" placeholder="e.g. INFY" style="width:120px;"></td>' +
    '<td><input class="entry-units" type="number" min="1" value="' + units + '" style="width:90px;"></td>' +
    '<td><input class="entry-price" type="number" step="0.05" value="' + price + '" style="width:100px;"></td>' +
    '<td><button type="button" class="danger small" onclick="this.closest(\\'tr\\').remove()">Remove</button></td>';
  tbody.appendChild(tr);
}}

async function submitManualIntent() {{
  const acc = document.getElementById('man-acc').value;
  const date = document.getElementById('man-date').value;
  const reason = document.getElementById('man-reason').value;
  const rows = document.querySelectorAll('#intent-entries tr');
  const entries = [];
  for (const r of rows) {{
    const sym = r.querySelector('.entry-symbol').value.trim();
    if (!sym) continue;
    entries.push({{
      type: r.querySelector('.entry-type').value,
      symbol: sym,
      units: parseInt(r.querySelector('.entry-units').value, 10),
      target_price: r.querySelector('.entry-price').value
    }});
  }}
  if (entries.length === 0) return alert('Add at least one valid entry with symbol.');
  const payload = {{ account_id: acc, action_date: date, reason: reason, entries: entries }};
  const token = getToken();
  const statusEl = document.getElementById('intent-status');
  statusEl.textContent = 'Submitting intent...';
  try {{
    const res = await fetch('/api/v2/actions/manual', {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/json', 'X-Operator-Token': token }},
      body: JSON.stringify(payload)
    }});
    const data = await res.json();
    if (!res.ok) throw Error(data.error || 'Submission failed');
    statusEl.textContent = 'Intent created successfully!';
    loadProposals();
  }} catch (e) {{ statusEl.textContent = e.message; }}
}}

document.getElementById('btn-load-proposals').addEventListener('click', loadProposals);
document.getElementById('add-entry-row').addEventListener('click', () => addIntentRow());
document.getElementById('submit-manual-intent').addEventListener('click', submitManualIntent);
addIntentRow('BUY', 'TCS', 10, '3800.00');
</script></body></html>"""
        return Response(page, mimetype="text/html")

    @blueprint.get("/backtest")
    def backtest_page() -> Response:
        today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
        start = (today - timedelta(days=90)).isoformat()
        end = (today - timedelta(days=1)).isoformat()
        page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Backtests — Stock Screener</title>{BASE_STYLE}</head><body>
{_render_nav("backtest")}
<h1>Backtest Replay & Performance Reports</h1>
<p class="muted">Run deterministic replays of weekly rankings against historical daily bars with costs and risk options.</p>

<div class="card">
  <div class="card-header">Replay Parameters</div>
  <div class="grid-4">
    <div class="form-group"><label>Strategy</label><select id="bt-strategy"><option value="strategy1">Strategy 1</option><option value="strategy2">Strategy 2</option></select></div>
    <div class="form-group"><label>Start Date</label><input id="bt-start" type="date" value="{start}"></div>
    <div class="form-group"><label>End Date</label><input id="bt-end" type="date" value="{end}"></div>
    <div class="form-group"><label>Starting Cash</label><input id="bt-cash" type="number" value="100000"></div>
  </div>

  <div class="grid-4" style="margin-top:0.75rem;">
    <div class="form-group"><label>Max Positions</label><input id="bt-positions" type="number" value="15" min="1" max="50"></div>
    <div class="form-group"><label>Rebalance Frequency</label><select id="bt-freq"><option value="DAILY">DAILY</option><option value="WEEKLY" selected>WEEKLY</option><option value="BIWEEKLY">BIWEEKLY</option><option value="MONTHLY">MONTHLY</option></select></div>
    <div class="form-group"><label>Data Basis</label><select id="bt-basis"><option value="UNADJUSTED">UNADJUSTED</option><option value="CORPORATE_ACTION_ADJUSTED">CORPORATE_ACTION_ADJUSTED</option></select></div>
    <div class="form-group"><label>Slippage (bps)</label><input id="bt-slippage" type="number" value="5"></div>
  </div>

  <div class="grid-4" style="margin-top:0.75rem;">
    <div class="form-group"><label>Fee (bps)</label><input id="bt-fee" type="number" value="3"></div>
    <div class="form-group"><label>Tax (bps)</label><input id="bt-tax" type="number" value="10"></div>
    <div class="form-group"><label>Min Market Cap</label><input id="bt-min-cap" type="number" value="0"></div>
    <div class="form-group"><label>Pyramid Fraction</label><input id="bt-pyramid-frac" type="number" step="0.1" value="0.5"></div>
  </div>

  <div class="form-row" style="margin-top:1rem;">
    <label style="display:flex;align-items:center;gap:0.4rem;"><input id="bt-daily-sl" type="checkbox" checked> Check Daily Stop Loss</label>
    <label style="display:flex;align-items:center;gap:0.4rem;"><input id="bt-midweek-buy" type="checkbox" checked> Allow Mid-Week Buys</label>
    <label style="display:flex;align-items:center;gap:0.4rem;"><input id="bt-pyramid" type="checkbox"> Enable Pyramiding</label>
  </div>

  <div class="form-row" style="margin-top:1rem;">
    <button id="btn-submit-replay" type="button" class="primary">Submit Replay Job</button>
    <button id="btn-load-reports" type="button" class="secondary">Load Saved Reports</button>
    <span id="bt-status" class="muted"></span>
  </div>
</div>

<div id="bt-report-card" class="card" style="display:none;">
  <div class="card-header">
    <span id="report-title">Backtest Report</span>
    <button class="secondary small" onclick="document.getElementById('bt-report-card').style.display='none'">Close</button>
  </div>
  <div class="grid-4" style="margin-bottom:1rem;">
    <div class="stat-card"><div class="stat-label">Total Return</div><div id="stat-return" class="stat-value">0%</div></div>
    <div class="stat-card"><div class="stat-label">Max Drawdown</div><div id="stat-drawdown" class="stat-value">0%</div></div>
    <div class="stat-card"><div class="stat-label">Sharpe Ratio</div><div id="stat-sharpe" class="stat-value">0.00</div></div>
    <div class="stat-card"><div class="stat-label">Trades / Fills</div><div id="stat-trades" class="stat-value">0</div></div>
  </div>
  <h3>Simulated Fills</h3>
  <table>
    <thead><tr><th>Date</th><th>Type</th><th>Instrument</th><th>Units</th><th>Price</th><th>Direction</th><th>Fee</th></tr></thead>
    <tbody id="report-fills"></tbody>
  </table>
</div>

<div class="card">
  <div class="card-header">Saved Backtest Runs</div>
  <table>
    <thead><tr><th>Run ID</th><th>Strategy</th><th>Range</th><th>Total Return</th><th>Max Drawdown</th><th>Created At</th><th>Actions</th></tr></thead>
    <tbody id="runs-table"><tr><td colspan="7" class="muted">Click Load Saved Reports to view previous runs.</td></tr></tbody>
  </table>
</div>

<script>
async function submitReplay() {{
  const statusEl = document.getElementById('bt-status');
  statusEl.textContent = 'Submitting backtest job...';
  const token = getToken();
  const payload = {{
    strategy_id: document.getElementById('bt-strategy').value,
    start_date: document.getElementById('bt-start').value,
    end_date: document.getElementById('bt-end').value,
    starting_cash: document.getElementById('bt-cash').value,
    max_positions: parseInt(document.getElementById('bt-positions').value, 10),
    rebalance_frequency: document.getElementById('bt-freq').value,
    data_basis: document.getElementById('bt-basis').value,
    slippage_bps: document.getElementById('bt-slippage').value,
    fee_bps: document.getElementById('bt-fee').value,
    tax_bps: document.getElementById('bt-tax').value,
    check_daily_sl: document.getElementById('bt-daily-sl').checked,
    mid_week_buy: document.getElementById('bt-midweek-buy').checked,
    enable_pyramiding: document.getElementById('bt-pyramid').checked,
    pyramid_fraction: document.getElementById('bt-pyramid-frac').value
  }};
  try {{
    const fingerprint = 'backtest:' + btoa(JSON.stringify(payload));
    const res = await fetch('/api/v2/operations/jobs', {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/json', 'X-Operator-Token': token }},
      body: JSON.stringify({{ fingerprint: fingerprint, kind: 'backtest.run', payload: payload }})
    }});
    const data = await res.json();
    if (!res.ok) throw Error(data.error || 'Submission failed');
    statusEl.textContent = 'Job submitted: ID #' + data.job_id + ' (' + data.status + ')';
    loadReports();
  }} catch (e) {{ statusEl.textContent = e.message; }}
}}

async function loadReports() {{
  const tbody = document.getElementById('runs-table');
  try {{
    const res = await fetch('/api/v2/backtests/runs?limit=50');
    const data = await res.json();
    if (!res.ok) throw Error(data.error || 'Failed to load runs');
    const runs = data.runs || [];
    tbody.replaceChildren();
    if (runs.length === 0) {{
      tbody.innerHTML = '<tr><td colspan="7" class="muted">No backtest runs found.</td></tr>';
      return;
    }}
    for (const r of runs) {{
      const tr = document.createElement('tr');
      const ret = Number(r.total_return);
      tr.innerHTML = '<td><code>' + r.run_id.slice(0, 8) + '...</code></td>' +
        '<td>' + r.strategy_id + '</td>' +
        '<td>' + r.start_date + ' &rarr; ' + r.end_date + '</td>' +
        '<td class="' + (ret >= 0 ? 'positive' : 'negative') + '">' + (ret >= 0 ? '+' : '') + (ret * 100).toFixed(2) + '%</td>' +
        '<td class="negative">-' + (Number(r.max_drawdown) * 100).toFixed(2) + '%</td>' +
        '<td>' + (r.created_at || '').slice(0, 19).replace('T', ' ') + '</td>' +
        '<td><div style="display:flex;gap:0.35rem;">' +
        '<button class="secondary small" onclick="viewRunReport(\\'' + r.run_id + '\\')">View</button>' +
        '<button class="danger small" onclick="deleteRun(\\'' + r.run_id + '\\')">Delete</button>' +
        '</div></td>';
      tbody.appendChild(tr);
    }}
  }} catch (e) {{ alert(e.message); }}
}}

async function viewRunReport(runId) {{
  try {{
    const res = await fetch('/api/v2/backtests/runs/' + encodeURIComponent(runId));
    const data = await res.json();
    if (!res.ok) throw Error(data.error || 'Failed to fetch report');
    document.getElementById('bt-report-card').style.display = 'block';
    document.getElementById('report-title').textContent = 'Backtest Run: ' + runId;
    const m = data.metrics || {{}};
    const ret = Number(m.total_return ?? 0);
    const dd = Number(m.max_drawdown ?? 0);
    document.getElementById('stat-return').textContent = (ret >= 0 ? '+' : '') + (ret * 100).toFixed(2) + '%';
    document.getElementById('stat-return').className = 'stat-value ' + (ret >= 0 ? 'positive' : 'negative');
    document.getElementById('stat-drawdown').textContent = '-' + (dd * 100).toFixed(2) + '%';
    document.getElementById('stat-sharpe').textContent = Number(m.sharpe_ratio ?? 0).toFixed(2);
    document.getElementById('stat-trades').textContent = data.fills ? data.fills.length : 0;

    const tbody = document.getElementById('report-fills');
    tbody.replaceChildren();
    for (const f of (data.fills || [])) {{
      const tr = document.createElement('tr');
      tr.innerHTML = '<td>' + f.as_of_date + '</td>' +
        '<td>' + f.decision_type + '</td>' +
        '<td>' + f.instrument_id + '</td>' +
        '<td>' + f.units + '</td>' +
        '<td>' + Number(f.execution_price).toFixed(2) + '</td>' +
        '<td><span class="badge ' + (f.direction === 'BUY' ? 'badge-green' : 'badge-amber') + '">' + f.direction + '</span></td>' +
        '<td>' + Number(f.fee || 0).toFixed(2) + '</td>';
      tbody.appendChild(tr);
    }}
  }} catch (e) {{ alert(e.message); }}
}}

async function deleteRun(runId) {{
  if (!confirm('Delete backtest run ' + runId + '?')) return;
  const token = getToken();
  try {{
    const res = await fetch('/api/v1/backtest/history/' + encodeURIComponent(runId), {{
      method: 'DELETE',
      headers: {{ 'X-Operator-Token': token }}
    }});
    if (!res.ok) {{
      const err = await res.json();
      throw Error(err.error || 'Delete failed');
    }}
    loadReports();
  }} catch (e) {{ alert(e.message); }}
}}

document.getElementById('btn-submit-replay').addEventListener('click', submitReplay);
document.getElementById('btn-load-reports').addEventListener('click', loadReports);
loadReports();
</script></body></html>"""
        return Response(page, mimetype="text/html")

    @blueprint.get("/portfolio")
    def portfolio_page() -> Response:
        today = datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
        page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Portfolio & Ledger — Stock Screener</title>{BASE_STYLE}</head><body>
{_render_nav("portfolio")}
<h1>Paper Portfolio Valuation & Ledger</h1>
<p class="muted">Real-time ledger accounting, open positions, capital adjustments, and transaction journal.</p>

<div class="card">
  <div class="card-header">Account Controls</div>
  <div class="form-row">
    <div class="form-group"><label>Account ID</label><input id="pt-acc" value="paper" style="width:120px;"></div>
    <div class="form-group"><label>As of Date</label><input id="pt-date" type="date" value="{today}"></div>
    <div class="form-group" style="justify-content:flex-end;">
      <button id="btn-load-valuation" class="primary">Load Valuation</button>
      <button id="btn-load-ticker" class="secondary">Load Live Ticker</button>
    </div>
  </div>
</div>

<div class="grid-4" style="margin-bottom:1.5rem;">
  <div class="stat-card"><div class="stat-label">Total Portfolio Value</div><div id="stat-total-val" class="stat-value">&#8377;0.00</div></div>
  <div class="stat-card"><div class="stat-label">Available Cash</div><div id="stat-cash" class="stat-value">&#8377;0.00</div></div>
  <div class="stat-card"><div class="stat-label">Equity Value</div><div id="stat-equity" class="stat-value">&#8377;0.00</div></div>
  <div class="stat-card"><div class="stat-label">Open Positions</div><div id="stat-positions" class="stat-value">0</div></div>
</div>

<div class="card">
  <div class="card-header">Current Holdings</div>
  <table>
    <thead><tr><th>Instrument / Symbol</th><th>Quantity</th><th>Avg Price</th><th>Current Price</th><th>Market Value</th><th>Stop Loss</th></tr></thead>
    <tbody id="holdings-body"><tr><td colspan="6" class="muted">Click Load Valuation to inspect portfolio positions.</td></tr></tbody>
  </table>
</div>

<div class="grid-2">
  <div class="card">
    <div class="card-header">Deposit / Withdraw Cash</div>
    <p class="muted" style="font-size:0.85rem;">Adjust ledger cash balance via paper capital events.</p>
    <div class="form-row">
      <div class="form-group"><label>Type</label><select id="cash-type"><option value="DEPOSIT">Deposit</option><option value="WITHDRAW">Withdraw</option></select></div>
      <div class="form-group"><label>Amount (INR)</label><input id="cash-amt" type="number" step="100" value="50000"></div>
    </div>
    <div class="form-row">
      <div class="form-group" style="flex:1;"><label>Note / Reference</label><input id="cash-note" value="Initial paper funding" placeholder="Description"></div>
      <button id="btn-submit-cash" class="success" style="margin-top:1.25rem;">Execute Transfer</button>
    </div>
    <p id="cash-status" class="muted"></p>
  </div>

  <div class="card">
    <div class="card-header">Transaction Journal</div>
    <div style="max-height:260px;overflow-y:auto;">
      <table>
        <thead><tr><th>Time</th><th>Event</th><th>Instrument</th><th>Units</th><th>Price</th><th>Balance</th></tr></thead>
        <tbody id="journal-body"><tr><td colspan="6" class="muted">Load valuation to see ledger entries.</td></tr></tbody>
      </table>
    </div>
  </div>
</div>

<script>
async function loadValuation() {{
  const acc = document.getElementById('pt-acc').value;
  const date = document.getElementById('pt-date').value;
  const token = getToken();
  try {{
    const res = await fetch('/api/v2/portfolio/accounts/' + encodeURIComponent(acc) + '/valuation?as_of_date=' + encodeURIComponent(date), {{
      headers: {{ 'X-Operator-Token': token }}
    }});
    const data = await res.json();
    if (!res.ok) throw Error(data.error || 'Failed to load valuation');
    
    document.getElementById('stat-total-val').textContent = '\\u20B9' + Number(data.total_value || 0).toLocaleString('en-IN', {{minimumFractionDigits:2, maximumFractionDigits:2}});
    document.getElementById('stat-cash').textContent = '\\u20B9' + Number(data.cash || 0).toLocaleString('en-IN', {{minimumFractionDigits:2, maximumFractionDigits:2}});
    document.getElementById('stat-equity').textContent = '\\u20B9' + Number(data.equity || 0).toLocaleString('en-IN', {{minimumFractionDigits:2, maximumFractionDigits:2}});
    document.getElementById('stat-positions').textContent = data.holdings ? data.holdings.length : 0;

    const tbody = document.getElementById('holdings-body');
    tbody.replaceChildren();
    if (!data.holdings || data.holdings.length === 0) {{
      tbody.innerHTML = '<tr><td colspan="6" class="muted">No open positions.</td></tr>';
    }} else {{
      for (const h of data.holdings) {{
        const tr = document.createElement('tr');
        tr.innerHTML = '<td><b>' + (h.symbol || h.instrument_id) + '</b></td>' +
          '<td>' + h.units + '</td>' +
          '<td>\\u20B9' + Number(h.average_price).toFixed(2) + '</td>' +
          '<td>\\u20B9' + Number(h.current_price || h.average_price).toFixed(2) + '</td>' +
          '<td>\\u20B9' + Number(h.market_value || (h.units * h.average_price)).toFixed(2) + '</td>' +
          '<td>\\u20B9' + Number(h.stop_loss || 0).toFixed(2) + '</td>';
        tbody.appendChild(tr);
      }}
    }}
    loadJournal(acc, token);
  }} catch (e) {{ alert(e.message); }}
}}

async function loadJournal(acc, token) {{
  try {{
    const res = await fetch('/api/v2/portfolio/accounts/' + encodeURIComponent(acc) + '/journal', {{
      headers: {{ 'X-Operator-Token': token }}
    }});
    const data = await res.json();
    if (!res.ok) return;
    const tbody = document.getElementById('journal-body');
    tbody.replaceChildren();
    const entries = data.journal || [];
    if (entries.length === 0) {{
      tbody.innerHTML = '<tr><td colspan="6" class="muted">No journal events recorded.</td></tr>';
      return;
    }}
    for (const j of entries) {{
      const tr = document.createElement('tr');
      tr.innerHTML = '<td>' + (j.timestamp || '').slice(0, 16).replace('T', ' ') + '</td>' +
        '<td><span class="badge ' + (j.type === 'BUY' ? 'badge-green' : j.type === 'SELL' ? 'badge-amber' : 'badge-blue') + '">' + j.type + '</span></td>' +
        '<td>' + (j.instrument_id || '-') + '</td>' +
        '<td>' + (j.units || '-') + '</td>' +
        '<td>' + (j.price ? '\\u20B9' + Number(j.price).toFixed(2) : '-') + '</td>' +
        '<td>' + (j.balance ? '\\u20B9' + Number(j.balance).toFixed(2) : '-') + '</td>';
      tbody.appendChild(tr);
    }}
  }} catch (e) {{ console.error(e); }}
}}

async function loadTicker() {{
  const acc = document.getElementById('pt-acc').value;
  const token = getToken();
  try {{
    const res = await fetch('/api/v2/portfolio/accounts/' + encodeURIComponent(acc) + '/ticker', {{
      headers: {{ 'X-Operator-Token': token }}
    }});
    const data = await res.json();
    if (!res.ok) throw Error(data.error || 'Failed to load ticker');
    alert('Ticker updated for ' + acc + ' with ' + (data.prices ? Object.keys(data.prices).length : 0) + ' instruments.');
    loadValuation();
  }} catch (e) {{ alert(e.message); }}
}}

async function submitCashTransfer() {{
  const acc = document.getElementById('pt-acc').value;
  const type = document.getElementById('cash-type').value;
  const amt = parseFloat(document.getElementById('cash-amt').value);
  const note = document.getElementById('cash-note').value;
  const statusEl = document.getElementById('cash-status');
  const token = getToken();
  statusEl.textContent = 'Processing transfer...';
  try {{
    const res = await fetch('/api/v1/investment/cash', {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/json', 'X-Operator-Token': token }},
      body: JSON.stringify({{ account_id: acc, type: type, amount: amt, note: note }})
    }});
    const data = await res.json();
    if (!res.ok) throw Error(data.error || 'Transfer failed');
    statusEl.textContent = 'Transfer completed: ' + type + ' \\u20B9' + amt;
    loadValuation();
  }} catch (e) {{ statusEl.textContent = e.message; }}
}}

document.getElementById('btn-load-valuation').addEventListener('click', loadValuation);
document.getElementById('btn-load-ticker').addEventListener('click', loadTicker);
document.getElementById('btn-submit-cash').addEventListener('click', submitCashTransfer);
loadValuation();
</script></body></html>"""
        return Response(page, mimetype="text/html")

    @blueprint.get("/configs")
    def configs_page() -> Response:
        today = datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
        page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Strategy Configurations — Stock Screener</title>{BASE_STYLE}</head><body>
{_render_nav("configs")}
<h1>Approved Strategy Configurations</h1>
<p class="muted">Inspect, create, approve, and activate immutable revisions of strategy sizing, risk limits, and factor weights.</p>

<div class="card">
  <div class="card-header">Active Configuration Lookup</div>
  <div class="form-row">
    <div class="form-group"><label>Strategy</label><select id="cfg-strat"><option value="strategy1">strategy1</option><option value="strategy2">strategy2</option></select></div>
    <div class="form-group"><label>As of Date</label><input id="cfg-date" type="date" value="{today}"></div>
    <div class="form-group" style="justify-content:flex-end;"><button id="btn-load-active" class="primary">Load Active Config</button></div>
  </div>
</div>

<div class="grid-2">
  <div class="card">
    <div class="card-header">
      <span>Active Settings</span>
      <span id="cfg-active-badge" class="badge badge-green">ACTIVE</span>
    </div>
    <p id="cfg-meta" class="muted" style="font-size:0.85rem;margin-bottom:1rem;">Click Load to inspect active parameters.</p>
    <table>
      <thead><tr><th>Parameter</th><th>Value</th></tr></thead>
      <tbody id="cfg-active-tbody"><tr><td colspan="2" class="muted">No configuration loaded.</td></tr></tbody>
    </table>
  </div>

  <div class="card">
    <div class="card-header">Create New Revision</div>
    <p class="muted" style="font-size:0.85rem;">Submit a draft configuration revision. Approving makes it candidate for activation.</p>
    <div class="grid-2">
      <div class="form-group"><label>Initial Capital</label><input id="edit-cap" value="100000"></div>
      <div class="form-group"><label>Risk Threshold</label><input id="edit-risk" value="1"></div>
      <div class="form-group"><label>Max Positions</label><input id="edit-pos" type="number" value="15" min="1" max="50"></div>
      <div class="form-group"><label>Min Position %</label><input id="edit-min-pos" value="0.05"></div>
      <div class="form-group"><label>Max Concentration %</label><input id="edit-max-conc" value="0.25"></div>
      <div class="form-group"><label>Exit Threshold</label><input id="edit-exit" value="40"></div>
      <div class="form-group"><label>Buffer %</label><input id="edit-buffer" value="0.25"></div>
      <div class="form-group"><label>SL Multiplier</label><input id="edit-sl-mult" value="2"></div>
      <div class="form-group"><label>Hard SL %</label><input id="edit-hard-sl" value="0.03"></div>
      <div class="form-group"><label>ATR Fallback %</label><input id="edit-atr" value="0.06"></div>
    </div>
    <div class="form-row" style="margin-top:1rem;">
      <button id="btn-create-rev" class="success">Save Draft Revision</button>
      <span id="rev-status" class="muted"></span>
    </div>
  </div>
</div>

<div class="card">
  <div class="card-header">Configuration Revisions</div>
  <table>
    <thead><tr><th>Revision ID</th><th>Strategy</th><th>Effective From</th><th>Status</th><th>Actions</th></tr></thead>
    <tbody id="revisions-tbody"><tr><td colspan="5" class="muted">Revisions will be loaded here.</td></tr></tbody>
  </table>
</div>

<script>
async function loadActiveConfig() {{
  const s = document.getElementById('cfg-strat').value;
  const d = document.getElementById('cfg-date').value;
  const tbody = document.getElementById('cfg-active-tbody');
  const meta = document.getElementById('cfg-meta');
  try {{
    const res = await fetch('/api/v2/configs/active/' + encodeURIComponent(s) + '?as_of_date=' + encodeURIComponent(d));
    const data = await res.json();
    if (!res.ok) throw Error(data.error || 'Failed to load configuration');
    meta.textContent = 'Revision: ' + data.revision_id + ' | Artifact: ' + (data.artifact_id || '').slice(0, 16) + '...';
    tbody.replaceChildren();
    const settings = data.settings || {{}};
    for (const [k, v] of Object.entries(settings)) {{
      if (k === 'factor_weights') continue;
      const tr = document.createElement('tr');
      tr.innerHTML = '<td><b>' + k + '</b></td><td>' + v + '</td>';
      tbody.appendChild(tr);
    }}
    if (settings.factor_weights) {{
      const tr = document.createElement('tr');
      tr.innerHTML = '<td><b>factor_weights</b></td><td><code>' + JSON.stringify(settings.factor_weights) + '</code></td>';
      tbody.appendChild(tr);
    }}
    // Populate editor fields
    if (settings.initial_capital) document.getElementById('edit-cap').value = settings.initial_capital;
    if (settings.risk_threshold) document.getElementById('edit-risk').value = settings.risk_threshold;
    if (settings.max_positions) document.getElementById('edit-pos').value = settings.max_positions;
    if (settings.min_position_percent) document.getElementById('edit-min-pos').value = settings.min_position_percent;
    if (settings.max_concentration_pct) document.getElementById('edit-max-conc').value = settings.max_concentration_pct;
    if (settings.exit_threshold) document.getElementById('edit-exit').value = settings.exit_threshold;
    if (settings.buffer_percent) document.getElementById('edit-buffer').value = settings.buffer_percent;
    if (settings.sl_multiplier) document.getElementById('edit-sl-mult').value = settings.sl_multiplier;
    if (settings.hard_sl_percent) document.getElementById('edit-hard-sl').value = settings.hard_sl_percent;
    if (settings.atr_fallback_percent) document.getElementById('edit-atr').value = settings.atr_fallback_percent;
  }} catch (e) {{ alert(e.message); }}
}}

async function createRevision() {{
  const s = document.getElementById('cfg-strat').value;
  const statusEl = document.getElementById('rev-status');
  statusEl.textContent = 'Saving revision...';
  const token = getToken();
  const settings = {{
    initial_capital: document.getElementById('edit-cap').value,
    risk_threshold: document.getElementById('edit-risk').value,
    max_positions: parseInt(document.getElementById('edit-pos').value, 10),
    min_position_percent: document.getElementById('edit-min-pos').value,
    max_concentration_pct: document.getElementById('edit-max-conc').value,
    exit_threshold: document.getElementById('edit-exit').value,
    buffer_percent: document.getElementById('edit-buffer').value,
    sl_multiplier: document.getElementById('edit-sl-mult').value,
    hard_sl_percent: document.getElementById('edit-hard-sl').value,
    atr_fallback_percent: document.getElementById('edit-atr').value
  }};
  try {{
    const res = await fetch('/api/v2/configs/revisions', {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/json', 'X-Operator-Token': token }},
      body: JSON.stringify({{ strategy_id: s, settings: settings }})
    }});
    const data = await res.json();
    if (!res.ok) throw Error(data.error || 'Failed to create revision');
    statusEl.textContent = 'Draft created: ' + data.revision_id;
    addRevisionRow(data);
  }} catch (e) {{ statusEl.textContent = e.message; }}
}}

function addRevisionRow(r) {{
  const tbody = document.getElementById('revisions-tbody');
  const tr = document.createElement('tr');
  tr.innerHTML = '<td><code>' + r.revision_id + '</code></td>' +
    '<td>' + r.strategy_id + '</td>' +
    '<td>' + (r.effective_from || 'None') + '</td>' +
    '<td><span class="badge badge-amber">' + r.status + '</span></td>' +
    '<td><div style="display:flex;gap:0.35rem;">' +
    '<button class="success small" onclick="approveRevision(\\'' + r.revision_id + '\\')">Approve</button>' +
    '<button class="primary small" onclick="activateRevision(\\'' + r.revision_id + '\\')">Set Effective</button>' +
    '</div></td>';
  tbody.prepend(tr);
}}

async function approveRevision(revId) {{
  const token = getToken();
  try {{
    const res = await fetch('/api/v2/configs/revisions/' + encodeURIComponent(revId) + '/approve', {{
      method: 'POST',
      headers: {{ 'X-Operator-Token': token }}
    }});
    const data = await res.json();
    if (!res.ok) throw Error(data.error || 'Approval failed');
    alert('Revision ' + revId + ' approved!');
  }} catch (e) {{ alert(e.message); }}
}}

async function activateRevision(revId) {{
  const token = getToken();
  const eff = prompt('Effective from ISO date (e.g. 2026-01-01):', '{today}');
  if (!eff) return;
  try {{
    const res = await fetch('/api/v2/configs/revisions/' + encodeURIComponent(revId) + '/effective', {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/json', 'X-Operator-Token': token }},
      body: JSON.stringify({{ effective_from: eff }})
    }});
    const data = await res.json();
    if (!res.ok) throw Error(data.error || 'Activation failed');
    alert('Revision ' + revId + ' effective from ' + eff);
    loadActiveConfig();
  }} catch (e) {{ alert(e.message); }}
}}

document.getElementById('btn-load-active').addEventListener('click', loadActiveConfig);
document.getElementById('btn-create-rev').addEventListener('click', createRevision);
loadActiveConfig();
</script></body></html>"""
        return Response(page, mimetype="text/html")

    @blueprint.get("/pipeline")
    def pipeline_page() -> Response:
        today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
        start = (today - timedelta(days=7)).isoformat()
        end = (today - timedelta(days=1)).isoformat()
        page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Research Pipeline — Stock Screener</title>{BASE_STYLE}</head><body>
{_render_nav("pipeline")}
<h1>Research Pipeline Orchestration</h1>
<p class="muted">Submit, monitor, retry, or cancel multi-stage data download, daily feature calculation, and weekly ranking jobs.</p>

<div class="card">
  <div class="card-header">Pipeline Submission & Control</div>
  <div class="form-row">
    <div class="form-group"><label>Start Date</label><input id="start" type="date" value="{start}"></div>
    <div class="form-group"><label>End Date</label><input id="end" type="date" value="{end}"></div>
    <label style="display:flex;align-items:center;gap:0.4rem;margin-top:1.25rem;">
      <input id="data" type="checkbox" checked> Sync Reference & Market Bars
    </label>
    <div class="form-group" style="justify-content:flex-end;">
      <button id="btn-submit-pipe" class="primary" onclick="submitRun()">Submit Pipeline</button>
    </div>
  </div>

  <div class="form-row" style="margin-top:0.75rem;">
    <input id="id" size="40" placeholder="Pipeline ID" style="flex:1;">
    <button onclick="load()" class="secondary">Load Pipeline</button>
    <button id="cancel" onclick="cancelRun()" class="danger" disabled>Cancel Pipeline</button>
  </div>

  <div style="margin-top:1rem;">
    <div style="display:flex;justify-content:space-between;margin-bottom:0.35rem;">
      <span id="status" class="muted">No pipeline selected.</span>
      <span id="pct-label" class="muted">0%</span>
    </div>
    <progress id='progress' max="100" value="0"></progress>
  </div>
</div>

<div class="card">
  <div class="card-header">Pipeline Stages</div>
  <table>
    <thead><tr><th>Stage</th><th>Status</th><th>Job ID</th><th>Action</th></tr></thead>
    <tbody id='stages'><tr><td colspan="4" class="muted">Submit or load a pipeline to inspect stage execution.</td></tr></tbody>
  </table>
</div>

<details class="card">
  <summary style="cursor:pointer;font-weight:600;">Raw Pipeline State</summary>
  <pre id="result"></pre>
</details>

<script>
function render(data) {{
  document.getElementById('id').value = data.pipeline_id || document.getElementById('id').value;
  const stages = data.stages || [];
  const done = stages.filter(s => ['SUCCEEDED', 'FAILED', 'CANCELLED'].includes(s.status)).length;
  const percent = stages.length ? Math.round(done * 100 / stages.length) : 0;
  document.getElementById('progress').value = percent;
  document.getElementById('pct-label').textContent = percent + '% (' + done + '/' + stages.length + ')';
  const status = document.getElementById('status');
  status.textContent = (data.status || 'UNKNOWN') + ' — ' + done + '/' + stages.length + ' stages terminal';
  status.className = data.status === 'SUCCEEDED' ? 'positive' : data.status === 'FAILED' ? 'negative' : 'muted';
  document.getElementById('cancel').disabled = !['RUNNING', 'QUEUED'].includes(data.status);
  
  const body = document.getElementById('stages');
  body.replaceChildren();
  for (const stage of stages) {{
    const row = document.createElement('tr');
    let badge = 'badge-gray';
    if (stage.status === 'SUCCEEDED') badge = 'badge-green';
    else if (stage.status === 'FAILED') badge = 'badge-red';
    else if (stage.status === 'RUNNING') badge = 'badge-blue';
    else if (stage.status === 'QUEUED') badge = 'badge-amber';
    row.innerHTML = '<td><b>' + stage.name + '</b></td>' +
      '<td><span class="badge ' + badge + '">' + stage.status + '</span></td>' +
      '<td>' + (stage.job_id || '-') + '</td>' +
      '<td>' + (stage.status === 'FAILED' ? '<button class="secondary small" onclick="retry(\\'' + stage.name + '\\')">Retry</button>' : '') + '</td>';
    body.appendChild(row);
  }}
  document.getElementById('result').textContent = JSON.stringify(data, null, 2);
}}

async function request(url, options = {{}}) {{
  const response = await fetch(url, {{
    ...options,
    headers: {{ ...(options.headers || {{}}), 'X-Operator-Token': getToken() }}
  }});
  const data = await response.json();
  if (!response.ok) throw Error(data.error || 'Pipeline request failed');
  return data;
}}

async function submitRun() {{
  try {{
    const data = await request('/api/v2/pipelines/research', {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify({{
        start_date: document.getElementById('start').value,
        end_date: document.getElementById('end').value,
        orchestrate_data: document.getElementById('data').checked
      }})
    }});
    render(data);
    poll();
  }} catch (error) {{ document.getElementById('status').textContent = error.message; }}
}}

async function load() {{
  try {{
    render(await request('/api/v2/pipelines/research/' + encodeURIComponent(document.getElementById('id').value), {{ headers: {{}} }}));
    poll();
  }} catch (error) {{ document.getElementById('status').textContent = error.message; }}
}}

async function retry(stage) {{
  try {{
    render(await request('/api/v2/pipelines/research/' + encodeURIComponent(document.getElementById('id').value) + '/stages/' + encodeURIComponent(stage) + '/retry', {{ method: 'POST' }}));
    poll();
  }} catch (error) {{ document.getElementById('status').textContent = error.message; }}
}}

async function cancelRun() {{
  if (!confirm('Cancel all non-terminal pipeline stages?')) return;
  try {{
    render(await request('/api/v2/pipelines/research/' + encodeURIComponent(document.getElementById('id').value) + '/cancel', {{ method: 'POST' }}));
  }} catch (error) {{ document.getElementById('status').textContent = error.message; }}
}}

async function poll() {{
  if (window.polling) return;
  window.polling = true;
  try {{
    for (let i = 0; i < 120; i++) {{
      await new Promise(resolve => setTimeout(resolve, 2000));
      const data = await request('/api/v2/pipelines/research/' + encodeURIComponent(document.getElementById('id').value), {{ headers: {{}} }});
      render(data);
      if (!['RUNNING', 'QUEUED'].includes(data.status)) break;
    }}
  }} catch (error) {{ document.getElementById('status').textContent = error.message; }}
  finally {{ window.polling = false; }}
}}
</script></body></html>"""
        return Response(page, mimetype="text/html")

    return blueprint
