"""Minimal browser shell over the versioned read-only APIs."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from flask import Blueprint, Response


def create_dashboard_blueprint() -> Blueprint:
    blueprint = Blueprint("dashboard_v2", __name__)

    @blueprint.get("/app")
    def dashboard() -> Response:
        today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
        last_friday = today - timedelta(days=(today.weekday() - 4) % 7)
        if last_friday >= today:
            last_friday -= timedelta(days=7)
        page = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Stock screener</title><style>
body{font:16px system-ui,sans-serif;max-width:1100px;margin:2rem auto;padding:0 1rem;color:#17212b}
nav{display:flex;gap:1rem}section{margin:2rem 0}input,select,button{font:inherit;padding:.35rem}
table{border-collapse:collapse;width:100%}th,td{text-align:left;border-bottom:1px solid #ddd;padding:.5rem}
.muted{color:#596673}pre{white-space:pre-wrap;overflow:auto;background:#f5f7f8;padding:1rem}
</style></head><body>
<nav><a href="/app">Overview</a><a href="/integrations/kite">Authorize Kite</a></nav>
<h1>Stock screener</h1><p class="muted">Research and paper-account view. No live order controls.</p>
<section><h2>Weekly rankings</h2>
<label>Week ending <input id="week" type="date" value="__WEEK__"></label>
<label>Strategy <select id="strategy"><option value="strategy1">Strategy 1</option>
<option value="strategy2">Strategy 2 (provisional)</option></select></label>
<button id="load-rankings">Load</button><p id="ranking-status" role="status"></p>
<table><thead><tr><th>Rank</th><th>Symbol</th><th>Score</th></tr></thead><tbody id="rankings"></tbody></table></section>
<section><h2>Index quotes</h2><p class="muted">Quotes are cached; stale labels mean a refresh job is needed.</p>
<button id="load-quotes">Load quotes</button><p id="quote-status" role="status"></p>
<table><thead><tr><th>Index</th><th>Last</th><th>Change %</th><th>Freshness</th></tr></thead>
<tbody id="quotes"></tbody></table></section>
<section><h2>Job lookup</h2><label>Job ID <input id="job-id" type="number" min="1"></label>
<button id="load-job">Look up</button><pre id="job-result"></pre></section>
<section><h2>Paper account</h2><label>Account ID <input id="account-id"></label>
<button id="load-account">Look up</button><pre id="account-result"></pre></section>
<section><h2>Paper action proposals</h2><p class="muted">Review decisions before approving.
Processing writes paper ledger fills; it never places broker orders.</p>
<label>Account ID <input id="action-account-id"></label>
<button id="load-actions">Load proposals</button><p id="action-status" role="status"></p>
<table><thead><tr><th>Date</th><th>Strategy</th><th>Status</th><th>Decisions</th><th>Review</th></tr></thead>
<tbody id="actions"></tbody></table><pre id="action-detail"></pre></section>
<script>
function cell(row,value){const node=document.createElement('td');node.textContent=String(value);row.appendChild(node)}
async function loadRankings(){
 const week=document.getElementById('week').value, strategy=document.getElementById('strategy').value;
 const status=document.getElementById('ranking-status'), body=document.getElementById('rankings');
 body.replaceChildren();status.textContent='Loading…';
 try{const response=await fetch('/api/v2/research/rankings?week_end='+encodeURIComponent(week)+'&strategy_id='+strategy+'&limit=50');
  const data=await response.json();if(!response.ok)throw Error(data.error||'Ranking request failed');
  for(const item of data.members){const row=document.createElement('tr');cell(row,item.rank);cell(row,item.symbol);
   cell(row,Number(item.score).toFixed(2));body.appendChild(row)}
  status.textContent=data.members.length+' rows. Strategy 2 research remains provisional.';
 }catch(error){status.textContent=error.message}}
async function loadQuotes(){
 const status=document.getElementById('quote-status'),body=document.getElementById('quotes');
 body.replaceChildren();status.textContent='Loading…';
 try{const response=await fetch('/api/v2/market/indices/quotes');const data=await response.json();
  if(!response.ok)throw Error(data.error||'Quote request failed');
  for(const item of data.quotes){const row=document.createElement('tr');cell(row,item.exchange+':'+item.symbol);
   cell(row,item.last_price);cell(row,Number(item.change_percent).toFixed(2));cell(row,item.freshness);
   body.appendChild(row)}status.textContent=data.quotes.length+' cached quotes';
 }catch(error){status.textContent=error.message}}
async function loadJob(){
 const id=document.getElementById('job-id').value,output=document.getElementById('job-result');
 if(!/^\\d+$/.test(id))return output.textContent='Enter a numeric job ID';
 const response=await fetch('/api/v2/operations/jobs/'+encodeURIComponent(id));
 output.textContent=JSON.stringify(await response.json(),null,2)}
async function loadAccount(){
 const id=document.getElementById('account-id').value,output=document.getElementById('account-result');
 if(!id)return output.textContent='Enter an account ID';
 const token=window.prompt('Local operator token');if(!token)return;
 const response=await fetch('/api/v2/portfolio/accounts/'+encodeURIComponent(id),
  {headers:{'X-Operator-Token':token}});output.textContent=JSON.stringify(await response.json(),null,2)}
async function loadActions(presetToken){
 const account=document.getElementById('action-account-id').value,
  status=document.getElementById('action-status'),body=document.getElementById('actions');
 body.replaceChildren();if(!account)return status.textContent='Enter an account ID';
 const token=typeof presetToken==='string'?presetToken:window.prompt('Local operator token');if(!token)return;
 try{const response=await fetch('/api/v2/actions/proposals?account_id='+encodeURIComponent(account),
  {headers:{'X-Operator-Token':token}}),data=await response.json();
  if(!response.ok)throw Error(data.error||'Proposal lookup failed');
  for(const proposal of data.proposals){const row=document.createElement('tr');
   cell(row,proposal.action_date);cell(row,proposal.strategy_id);cell(row,proposal.status);
   cell(row,proposal.decisions.map(item=>item.type+' '+(item.symbol||'')).join(', '));
   const control=document.createElement('td'),view=document.createElement('button');
   view.textContent='View';view.addEventListener('click',()=>{
    document.getElementById('action-detail').textContent=JSON.stringify(proposal,null,2)});
   control.appendChild(view);
   for(const [label,operation,allowed] of [['Approve','approve','PENDING'],
    ['Reject','reject','PENDING'],['Process','process','APPROVED']]){
    if(proposal.status!==allowed)continue;
    const button=document.createElement('button');button.textContent=label;
    button.addEventListener('click',async()=>{
     if(!window.confirm(label+' paper proposal '+proposal.proposal_id+'?'))return;
     const result=await fetch('/api/v2/actions/proposals/'+encodeURIComponent(proposal.proposal_id)+'/'+operation,
      {method:'POST',headers:{'X-Operator-Token':token}}),detail=await result.json();
     document.getElementById('action-detail').textContent=JSON.stringify(detail,null,2);
     if(result.ok)loadActions(token);else status.textContent=detail.error||'Action failed';});
    control.appendChild(button)}row.appendChild(control);body.appendChild(row)}
  status.textContent=data.proposals.length+' proposals';
 }catch(error){status.textContent=error.message}}
document.getElementById('load-rankings').addEventListener('click',loadRankings);
document.getElementById('load-quotes').addEventListener('click',loadQuotes);
document.getElementById('load-job').addEventListener('click',loadJob);
document.getElementById('load-account').addEventListener('click',loadAccount);
document.getElementById('load-actions').addEventListener('click',loadActions);
loadRankings();loadQuotes();
</script></body></html>"""
        return Response(page.replace("__WEEK__", last_friday.isoformat()), mimetype="text/html")

    return blueprint
