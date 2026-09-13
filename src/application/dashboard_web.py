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

    @blueprint.get("/actions")
    def actions_page() -> Response:
        return Response(
            """<!doctype html><html><head><title>Actions</title></head><body>
            <nav><a href='/app'>Overview</a> <a href='/backtest'>Backtests</a></nav>
            <h1>Paper actions</h1><p>Reviewable proposals are loaded from the v4 actions API.</p>
            <label>Account <input id='account' value='paper'></label><button onclick='load()'>Load</button>
            <h2>Manual intent</h2><p>Paste a validated batch intent JSON; creation does not fill the ledger.</p>
            <textarea id='manual' rows='8' cols='80'>{"account_id":"paper","action_date":"","entries":[],"reason":""}</textarea><button onclick='manual()'>Create intent</button>
            <pre id='result'></pre><script>async function load(){const id=document.getElementById('account').value;
            const token=prompt('Local operator token');if(!token)return;const r=await fetch('/api/v2/actions/proposals?account_id='+encodeURIComponent(id),{headers:{'X-Operator-Token':token}});document.getElementById('result').textContent=JSON.stringify(await r.json(),null,2)}</script>
            <script>async function manual(){const token=prompt('Local operator token');if(!token)return;try{const r=await fetch('/api/v2/actions/manual',{method:'POST',headers:{'Content-Type':'application/json','X-Operator-Token':token},body:document.getElementById('manual').value});document.getElementById('result').textContent=JSON.stringify(await r.json(),null,2)}catch(e){document.getElementById('result').textContent=e.message}}</script>
            </body></html>""",
            mimetype="text/html",
        )

    @blueprint.get("/backtest")
    def backtest_page() -> Response:
        return Response(
            """<!doctype html><html><head><title>Backtests</title></head><body>
            <nav><a href='/app'>Overview</a> <a href='/actions'>Actions</a></nav>
            <h1>Backtest reports</h1><p>Submit a durable replay job or inspect immutable reports.</p>
            <textarea id='command' rows='7' cols='90'>{"strategy_id":"strategy1","start_date":"","end_date":"","starting_cash":"100000","max_positions":15,"slippage_bps":"0","fee_bps":"0","data_basis":"UNADJUSTED"}</textarea><br><button onclick='submitRun()'>Submit replay</button><button onclick='load()'>Load reports</button>
            <pre id='result'></pre><script>function token(){return prompt('Local operator token')||''}
            async function submitRun(){const t=token();if(!t)return;const payload=JSON.parse(document.getElementById('command').value);const fingerprint='backtest:'+btoa(JSON.stringify(payload));const r=await fetch('/api/v2/operations/jobs',{method:'POST',headers:{'Content-Type':'application/json','X-Operator-Token':t},body:JSON.stringify({fingerprint:fingerprint,kind:'backtest.run',payload:payload})});document.getElementById('result').textContent=JSON.stringify(await r.json(),null,2)}
            async function load(){const r=await fetch('/api/v2/backtests/runs?limit=50');document.getElementById('result').textContent=JSON.stringify(await r.json(),null,2)}</script>
            </body></html>""",
            mimetype="text/html",
        )

    @blueprint.get("/pipeline")
    def pipeline_page() -> Response:
        return Response(
            """<!doctype html><html><head><title>Research pipeline</title><style>
            body{font:16px system-ui,sans-serif;max-width:1100px;margin:2rem auto;padding:0 1rem;color:#17212b}
            nav{display:flex;gap:1rem}input,button{font:inherit;padding:.35rem}progress{width:100%;height:1.25rem}
            table{border-collapse:collapse;width:100%;margin-top:1rem}th,td{text-align:left;border-bottom:1px solid #ddd;padding:.5rem}
            .muted{color:#596673}.ok{color:#176b35}.bad{color:#a02020}
            </style></head><body>
            <nav><a href='/app'>Overview</a> <a href='/configs'>Configs</a> <a href='/portfolio'>Portfolio</a></nav>
            <h1>Research pipeline</h1><p>Submit and inspect durable pipeline stages.</p>
            <label>Start <input id='start' type='date'></label><label>End <input id='end' type='date'></label>
            <label><input id='data' type='checkbox' checked> Sync reference and market data</label>
            <button onclick='submitRun()'>Submit</button><input id='id' size='40' placeholder='Pipeline ID'><button onclick='load()'>Load</button>
            <p id='status' role='status' class='muted'>No pipeline selected.</p><progress id='progress' max='100' value='0'></progress>
            <p><button id='cancel' onclick='cancelRun()' disabled>Cancel pipeline</button></p>
            <table><thead><tr><th>Stage</th><th>Status</th><th>Job</th><th>Control</th></tr></thead><tbody id='stages'></tbody></table>
            <details><summary>Raw response</summary><pre id='result'></pre></details><script>
            let operatorToken='';
            function token(){operatorToken=operatorToken||prompt('Local operator token')||'';return operatorToken}
            function render(data){
              document.getElementById('id').value=data.pipeline_id||document.getElementById('id').value;
              const stages=data.stages||[],done=stages.filter(s=>['SUCCEEDED','FAILED','CANCELLED'].includes(s.status)).length;
              const percent=stages.length?Math.round(done*100/stages.length):0;
              document.getElementById('progress').value=percent;
              const status=document.getElementById('status');status.textContent=(data.status||'UNKNOWN')+' — '+done+'/'+stages.length+' stages terminal ('+percent+'%)';
              status.className=data.status==='SUCCEEDED'?'ok':data.status==='FAILED'?'bad':'muted';
              document.getElementById('cancel').disabled=!['RUNNING','QUEUED'].includes(data.status);
              const body=document.getElementById('stages');body.replaceChildren();
              for(const stage of stages){const row=document.createElement('tr');
                for(const value of [stage.name,stage.status,stage.job_id]){const cell=document.createElement('td');cell.textContent=value;row.appendChild(cell)}
                const control=document.createElement('td');
                if(stage.status==='FAILED'){const button=document.createElement('button');button.textContent='Retry';button.onclick=()=>retry(stage.name);control.appendChild(button)}
                row.appendChild(control);body.appendChild(row)}
              document.getElementById('result').textContent=JSON.stringify(data,null,2);
            }
            async function request(url,options={}){const response=await fetch(url,{...options,headers:{...(options.headers||{}),'X-Operator-Token':token()}});const data=await response.json();if(!response.ok)throw Error(data.error||'Pipeline request failed');return data}
            async function submitRun(){try{const data=await request('/api/v2/pipelines/research',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({start_date:document.getElementById('start').value,end_date:document.getElementById('end').value,orchestrate_data:document.getElementById('data').checked})});render(data);poll()}catch(error){document.getElementById('status').textContent=error.message}}
            async function load(){try{render(await request('/api/v2/pipelines/research/'+encodeURIComponent(document.getElementById('id').value),{headers:{}}));poll()}catch(error){document.getElementById('status').textContent=error.message}}
            async function retry(stage){try{render(await request('/api/v2/pipelines/research/'+encodeURIComponent(document.getElementById('id').value)+'/stages/'+encodeURIComponent(stage)+'/retry',{method:'POST'}));poll()}catch(error){document.getElementById('status').textContent=error.message}}
            async function cancelRun(){if(!confirm('Cancel all non-terminal pipeline stages?'))return;try{render(await request('/api/v2/pipelines/research/'+encodeURIComponent(document.getElementById('id').value)+'/cancel',{method:'POST'}))}catch(error){document.getElementById('status').textContent=error.message}}
            async function poll(){if(window.polling)return;window.polling=true;try{for(let i=0;i<120;i++){await new Promise(resolve=>setTimeout(resolve,2000));const data=await request('/api/v2/pipelines/research/'+encodeURIComponent(document.getElementById('id').value),{headers:{}});render(data);if(!['RUNNING','QUEUED'].includes(data.status))break}}catch(error){document.getElementById('status').textContent=error.message}finally{window.polling=false}}
            </script></body></html>""",
            mimetype="text/html",
        )

    @blueprint.get("/configs")
    def configs_page() -> Response:
        return Response(
            """<!doctype html><html><head><title>Strategy configs</title></head><body>
            <nav><a href='/app'>Overview</a> <a href='/pipeline'>Pipeline</a> <a href='/portfolio'>Portfolio</a></nav>
            <h1>Approved strategy configurations</h1><label>Strategy <select id='strategy'><option>strategy1</option><option>strategy2</option></select></label>
            <label>As of <input id='date' type='date'></label><button onclick='load()'>Load</button><pre id='result'></pre>
            <script>async function load(){const s=document.getElementById('strategy').value,d=document.getElementById('date').value;const r=await fetch('/api/v2/configs/active/'+s+'?as_of_date='+encodeURIComponent(d));document.getElementById('result').textContent=JSON.stringify(await r.json(),null,2)}</script>
            </body></html>""",
            mimetype="text/html",
        )

    @blueprint.get("/portfolio")
    def portfolio_page() -> Response:
        return Response(
            """<!doctype html><html><head><title>Portfolio</title></head><body>
            <nav><a href='/app'>Overview</a> <a href='/actions'>Actions</a> <a href='/backtest'>Backtests</a></nav>
            <h1>Portfolio valuation and journal</h1><label>Account <input id='account' value='paper'></label><label>As of <input id='date' type='date'></label><button onclick='load()'>Load dated view</button><button onclick='loadTicker()'>Load current ticker</button><pre id='result'></pre>
            <script>function account(){return encodeURIComponent(document.getElementById('account').value)}function auth(){const t=prompt('Local operator token');return t?{'X-Operator-Token':t}:null}
            async function load(){const a=account(),d=document.getElementById('date').value,h=auth();if(!h)return;const v=await fetch('/api/v2/portfolio/accounts/'+a+'/valuation?as_of_date='+encodeURIComponent(d),{headers:h}),j=await fetch('/api/v2/portfolio/accounts/'+a+'/journal',{headers:h});document.getElementById('result').textContent=JSON.stringify({valuation:await v.json(),journal:await j.json()},null,2)}
            async function loadTicker(){const h=auth();if(!h)return;const r=await fetch('/api/v2/portfolio/accounts/'+account()+'/ticker',{headers:h});document.getElementById('result').textContent=JSON.stringify(await r.json(),null,2)}</script>
            </body></html>""",
            mimetype="text/html",
        )

    return blueprint
