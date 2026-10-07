(() => {
  const $ = id => document.getElementById(id);
  let request, generation = 0, generationPoll;
  const statusNames = {PENDING:"Awaiting review", APPROVED:"Approved", REJECTED:"Rejected", PROCESSED:"Recorded"};
  const strategyNames = new Map();
  function actionButton(label, action, style = "secondary") {
    const button = document.createElement("button"); button.textContent = label; button.className = style; button.type = "button";
    button.onclick = async () => { button.disabled = true; try { await action(); } catch (error) { $("actions-error").textContent = error.message; } finally { button.disabled = false; } };
    return button;
  }
  async function dates() {
    const account = $("account").value; if (!account) return;
    const data = await Screener.api(`/api/actions/proposals/dates?account_id=${encodeURIComponent(account)}`);
    const selected = $("action-date").value;
    $("action-date").replaceChildren(new Option("All dates", ""), ...data.action_dates.map(day => new Option(day, day)));
    if (data.action_dates.includes(selected)) $("action-date").value = selected;
  }
  function renderRisk(projections) {
    const host = $("risk");
    if (!projections?.length) { host.innerHTML = '<p class="workflow-empty">No saved risk projections found for this account and date.</p>'; return; }
    host.replaceChildren(...projections.map(projection => {
      const card = document.createElement("article"); card.className = "risk-card";
      const header = document.createElement("div"); header.className = "risk-card-heading";
      const date = document.createElement("strong"); date.textContent = projection.action_date || "Risk projection";
      const quality = document.createElement("span"); quality.className = "workflow-chip"; quality.textContent = projection.quality || "Saved";
      header.append(date, quality); card.append(header);
      const grid = document.createElement("dl"); grid.className = "risk-fields";
      const skip = new Set(["account_id", "action_date", "quality", "artifact_id"]);
      Object.entries(projection).filter(([key, value]) => !skip.has(key) && ["string", "number", "boolean"].includes(typeof value)).forEach(([key, value]) => {
        const row = document.createElement("div"), term = document.createElement("dt"), detail = document.createElement("dd");
        term.textContent = key.replaceAll("_", " "); detail.textContent = String(value); row.append(term, detail); grid.append(row);
      });
      card.append(grid); return card;
    }));
  }
  function renderProposal(proposal) {
    const strategy = proposal.strategy_id === "portfolio_stop" ? "Portfolio stops" : strategyNames.get(proposal.strategy_id) || proposal.strategy_id || "Unknown";
    const decisions = proposal.decisions || [];
    const states = proposal.decision_statuses || decisions.map(() => proposal.status || "PENDING");
    return decisions.map((decision, index) => {
      const strategyLabel = document.createElement("span"); strategyLabel.className = "strategy-chip"; strategyLabel.textContent = strategy;
      const symbol = document.createElement("strong"); symbol.className = "stock-symbol"; symbol.textContent = decision.symbol || decision.instrument_id || "Portfolio";
      const side = document.createElement("span"); side.className = `trade-side ${String(decision.type || "").toLowerCase()}`; side.textContent = decision.type || "Action";
      let signalQuality = "—";
      if (proposal.strategy_id === "momentum" && decision.score != null) {
        signalQuality = Number(decision.score).toLocaleString("en-IN", {maximumFractionDigits:2});
      } else if (proposal.strategy_id === "positional_trend_following" && decision.adx != null) {
        signalQuality = `ADX ${Number(decision.adx).toLocaleString("en-IN", {maximumFractionDigits:1})}`;
      }
      const rank = decision.rank ?? decision.signal_rank;
      const rankLabel = rank == null ? "—" : `#${rank}`;
      const stateValue = states[index] || "PENDING";
      const state = document.createElement("span"); state.className = `status-chip status-${String(stateValue).toLowerCase()}`; state.textContent = statusNames[stateValue] || stateValue;
      const review = document.createElement("div"); review.className = "proposal-review-actions";
      if (proposal.strategy_id === "portfolio_stop") {
        side.textContent = "SELL";
        const order = proposal.broker_order;
        if (order) state.textContent = order.status;
        const id = encodeURIComponent(proposal.proposal_id);
        if (["PENDING", "APPROVED"].includes(proposal.status) && (!order || order.status === "LOCAL_CREATED")) {
          review.append(actionButton(proposal.status === "APPROVED" ? "Submit approved sell on Kite" : "Approve & sell on Kite", async () => {
            const result = await Screener.api(`/api/actions/stops/${id}/approve-execute`, {method:"POST",body:JSON.stringify({approved:true})});
            await load();
            $("generation-status").textContent = `Kite order ${result.order.broker_order_id || result.order.order_id}: ${result.order.status}. Confirmed fills update the portfolio journal.`;
          }, ""));
          if (proposal.status === "PENDING") review.append(actionButton("Reject", async () => { await Screener.api(`/api/actions/proposals/${id}/reject`, {method:"POST"}); await load(); }));
        }
        if (order && !["FILLED", "CANCELLED", "REJECTED", "LOCAL_CREATED"].includes(order.status)) review.append(actionButton("Refresh Kite order", async () => {
          await Screener.api(`/api/actions/stops/${id}/reconcile`, {method:"POST"}); await load();
        }));
      } else if (stateValue === "PENDING" && decision.type !== "NO_ACTION") {
        if (proposal.strategy_id === "manual") review.append(actionButton("Approve", async () => { await Screener.api(`/api/actions/proposals/${encodeURIComponent(proposal.proposal_id)}/decisions/${index}/approve`, {method:"POST"}); await load(); }, ""));
        else review.append(actionButton("Approve & execute on Kite", async () => {
          const result = await Screener.api(`/api/actions/proposals/${encodeURIComponent(proposal.proposal_id)}/approve-execute`, {method:"POST",body:JSON.stringify({approved:true,decision_index:index})});
          await load(); $("generation-status").textContent = result.execution?.last_error || (result.status === "PENDING" ? "Stock approved. Execution waits until every stock in this proposal is reviewed." : `Execution ${result.execution?.status || "queued"} for session ${result.action_date}. Confirmed fills update the journal.`);
        }, ""));
        review.append(actionButton("Reject", async () => { await Screener.api(`/api/actions/proposals/${encodeURIComponent(proposal.proposal_id)}/decisions/${index}/reject`, {method:"POST"}); await load(); }, "secondary"));
      } else if (stateValue === "APPROVED" && proposal.status === "APPROVED") {
        const firstApproved = states.findIndex(value => value === "APPROVED") === index;
        if (firstApproved && proposal.strategy_id === "manual") review.append(actionButton("Record confirmed fills", async () => {
          if (!confirm("Confirm these quantities and prices were actually executed?")) return;
          await Screener.api(`/api/actions/proposals/${encodeURIComponent(proposal.proposal_id)}/process`, {method:"POST"}); await load();
        }));
        if (firstApproved && proposal.strategy_id !== "manual") review.append(actionButton(proposal.execution?.status === "BLOCKED" ? "Retry approved execution on Kite" : proposal.execution ? "Refresh execution" : "Execute approved actions on Kite", async () => {
          const path = proposal.execution && proposal.execution.status !== "BLOCKED" ? "execution-refresh" : "approve-execute";
          const result = await Screener.api(`/api/actions/proposals/${encodeURIComponent(proposal.proposal_id)}/${path}`, {method:"POST", ...(path === "approve-execute" ? {body:JSON.stringify({approved:true})} : {})});
          await load(); $("generation-status").textContent = result.execution?.last_error || `Execution ${result.execution?.status || "queued"} for ${result.action_date}.`;
        }));
      } else if (decision.type === "NO_ACTION") {
        const note = document.createElement("span"); note.className = "muted"; note.textContent = "No stock action"; review.append(note);
      }
      if (decision.type === "NO_ACTION") { state.textContent = "No action"; state.className = "status-chip"; }
      const brokerOrder = proposal.broker_orders?.find(order => order.instrument_id === decision.instrument_id);
      if (brokerOrder) state.textContent = brokerOrder.status;
      else if (proposal.execution && proposal.strategy_id !== "portfolio_stop" && stateValue === "APPROVED") state.textContent = proposal.execution.status;
      if (proposal.execution?.last_error) state.title = proposal.execution.last_error;
      return Screener.row([strategyLabel, symbol, side, signalQuality, rankLabel, decision.units ?? "—", decision.execution_price ? `₹${Number(decision.execution_price).toLocaleString("en-IN", {maximumFractionDigits:2})}` : "—", decision.reason || "—", decision.signal_date || proposal.action_date || "—", state, review]);
    });
  }
  async function load() {
    request?.abort(); request = new AbortController(); const token = ++generation, account = $("account").value;
    if (!account) return;
    $("proposals").innerHTML = '<tr><td colspan="11" class="workflow-empty">Loading proposals…</td></tr>';
    $("actions-error").textContent = "";
    $("stop-check-error").textContent = "";
    const query = new URLSearchParams({account_id:account});
    if ($("action-date").value) query.set("action_date", $("action-date").value);
    if ($("proposal-strategy").value) query.set("strategy_id", $("proposal-strategy").value);
    const strategyLabel = $("proposal-strategy").selectedOptions[0]?.textContent || "All strategies";
    $("proposal-filter-caption").textContent = `${strategyLabel} · ${$("action-date").value || "All dates"}`;
    try {
    const riskQuery = new URLSearchParams({account_id:account}); if ($("action-date").value) riskQuery.set("action_date", $("action-date").value);
      try {
        const stops = await Screener.api("/api/actions/stops/check", {method:"POST", body:JSON.stringify({account_id:account}), signal:request.signal});
        if (token !== generation || account !== $("account").value) return;
        $("stop-proposals").replaceChildren(...(stops.proposals || []).flatMap(renderProposal));
        const money = value => value == null ? "—" : `₹${Number(value).toLocaleString("en-IN", {maximumFractionDigits:2})}`;
        $("stop-checks").replaceChildren(...(stops.checks || []).map(check => Screener.row([check.symbol, money(check.price), money(check.stop_threshold), check.price_source ? `${check.price_source === "live_kite" ? "Live Kite" : "Stored close"} · ${check.price_date}` : "—", ({above_stop:"Above stop", breached:"Stop breached", review_exists:"Sell review exists", stop_unavailable:check.reason || "Stop unavailable"})[check.status] || check.status])));
        $("stop-check-note").textContent = stops.proposals?.length ? `${stops.proposals.length} stop sell reviews. Orders require your approval; confirmed fills update the portfolio.` : "No current stop breaches at the checked prices. Expand the checks below to see each price, threshold and source.";
        if (!stops.proposals?.length) { const row = document.createElement("tr"), cell = document.createElement("td"); cell.colSpan = 11; cell.className = "workflow-empty"; cell.textContent = "No stop sell action currently requires review."; row.append(cell); $("stop-proposals").append(row); }
      } catch (error) {
        if (error.name === "AbortError") return;
        $("stop-proposals").replaceChildren(); $("stop-checks").replaceChildren();
        $("stop-check-note").textContent = "Stop check unavailable.";
        $("stop-check-error").textContent = error.message;
      }
      if (token !== generation || account !== $("account").value) return;
      await dates();
      if ($("action-date").value) query.set("action_date", $("action-date").value); else query.delete("action_date");
      const data = await Screener.api(`/api/actions/proposals?${query}`, {signal:request.signal});
      if (token !== generation || account !== $("account").value) return;
      const proposals = data.proposals || [];
      $("proposals").replaceChildren(...proposals.flatMap(renderProposal));
      if (!proposals.length) {
        const empty = document.createElement("tr"), cell = document.createElement("td"); cell.colSpan = 11; cell.className = "workflow-empty";
        cell.textContent = "No proposals match this account and date. Generate actions above, or load another date."; empty.append(cell); $("proposals").append(empty);
      }
      const counts = {PENDING:0, APPROVED:0, REJECTED:0};
      proposals.forEach(item => (item.decision_statuses || []).forEach(state => { counts[state] = (counts[state] || 0) + 1; }));
      const stockCount = proposals.reduce((sum, item) => sum + (item.decisions || []).length, 0);
      $("proposal-summary").replaceChildren(...[["Stocks shown", String(stockCount)], ["Awaiting review", String(counts.PENDING)], ["Approved", String(counts.APPROVED)], ["Rejected", String(counts.REJECTED)]].map(([label, value]) => {
        const stat = document.createElement("div"); stat.className = "workflow-stat"; const n = document.createElement("strong"); n.textContent = value; const l = document.createElement("span"); l.textContent = label; stat.append(n, l); return stat;
      }));
      try {
        const risk = await Screener.api(`/api/actions/risk?${riskQuery}`, {signal:request.signal});
        if (token === generation) renderRisk(risk.projections || []);
      } catch (error) { if (error.name !== "AbortError") renderRisk([]); }
      $("actions-error").textContent = "";
    } catch (error) { if (error.name !== "AbortError" && token === generation) $("actions-error").textContent = error.message; }
  }
  async function generate() {
    const status = $("generation-status"), target = $("generate-date").value;
    if (!$("account").value) { status.textContent = "Choose a portfolio account first."; return; }
    if (!target) { status.textContent = "Choose the target trading session."; return; }
    const button = $("generate-actions"); button.disabled = true; $("start-action-worker").hidden = true;
    status.textContent = "Finding the latest completed NSE session…";
    try {
      const source = await Screener.api(`/api/actions/sessions/latest?action_date=${encodeURIComponent(target)}`);
      const payload = {account_id:$("account").value, strategy_id:$("generate-strategy").value, action_date:target, as_of_date:source.as_of_date};
      const fingerprint = `portfolio-action:${payload.account_id}:${payload.strategy_id}:${payload.as_of_date}:${payload.action_date}`;
      const job = await Screener.api("/api/operations/jobs", {method:"POST",body:JSON.stringify({fingerprint,kind:"actions.generate-portfolio-proposal",payload})});
      status.textContent = `Proposal generation queued for ${target}, using the ${source.as_of_date} close. Job ${job.job_id} is ${job.status.toLowerCase()}.`;
      const worker = await Screener.api("/api/operations/worker/status");
      if (!worker.running) $("start-action-worker").hidden = false;
      clearInterval(generationPoll);
      generationPoll = setInterval(async () => {
        try {
          const current = await Screener.api(`/api/operations/jobs/${job.job_id}`);
          if (["SUCCEEDED", "FAILED", "CANCELLED"].includes(current.status)) {
            clearInterval(generationPoll);
            if (current.status === "SUCCEEDED") {
              status.textContent = `Proposal generation completed for ${target}. Loading the new proposal…`;
              await dates();
              if ([...$("action-date").options].some(option => option.value === target)) $("action-date").value = target;
              await load(); status.textContent = `Actions generated for ${target} from the ${source.as_of_date} close. Review the proposal before taking any next step.`;
            } else status.textContent = `Generation ${current.status.toLowerCase()}: ${current.last_error || "check the job details on Pipeline"}`;
          }
        } catch (error) { clearInterval(generationPoll); status.textContent = error.message; }
      }, 2000);
    } catch (error) { status.textContent = error.message || "Could not queue proposal generation."; }
    finally { button.disabled = false; }
  }
  function manual() {
    const modal = $("app-modal"), host = $("modal-content"); host.replaceChildren();
    const title = document.createElement("h2"); title.id = "modal-title"; title.textContent = "Record a manual trade";
    const intro = document.createElement("p"); intro.className = "muted"; intro.textContent = "Enter a trade that has already been executed. It will be added to the review queue first.";
    const form = document.createElement("form"); form.className = "manual-trade-form"; const fields = {};
    for (const [key, label, type] of [["date","Execution date","date"],["symbol","NSE symbol","text"],["units","Whole units","number"],["price","Actual unit price","number"],["reason","Reason or execution evidence","text"]]) {
      const field = document.createElement("label"); field.textContent = label; const input = document.createElement("input"); input.type = type; input.required = true;
      if (type === "number") { input.min = "0"; input.step = key === "units" ? "1" : "0.01"; }
      field.append(input); form.append(field); fields[key] = input;
    }
    const sideField = document.createElement("label"); sideField.textContent = "Trade side"; const side = document.createElement("select"); side.append(new Option("Buy", "BUY"), new Option("Sell", "SELL")); sideField.append(side); form.append(sideField);
    const submit = document.createElement("button"); submit.type = "submit"; submit.textContent = "Create trade for review"; form.append(submit);
    form.onsubmit = async event => {
      event.preventDefault(); submit.disabled = true;
      try { await Screener.api("/api/actions/manual", {method:"POST",body:JSON.stringify({account_id:$("account").value,action_date:fields.date.value,reason:fields.reason.value,entries:[{symbol:fields.symbol.value.trim().toUpperCase(),exchange:"NSE",side:side.value,units:Number(fields.units.value),price:fields.price.value}]})}); modal.close(); await dates(); await load(); }
      catch (error) { $("actions-error").textContent = error.message; } finally { submit.disabled = false; }
    };
    host.append(title, intro, form); modal.showModal(); fields.date.focus();
  }
  document.addEventListener("DOMContentLoaded", async () => {
    try {
      const [data, strategyData] = await Promise.all([Screener.api("/api/portfolio/accounts"), Screener.api("/api/strategies/active")]);
      $("account").replaceChildren(...(data.accounts || []).map(account => new Option(account.display_name || account.account_id, account.account_id)));
      const strategies = strategyData.strategies || [];
      strategies.forEach(strategy => strategyNames.set(strategy.strategy_id, strategy.definition.strategy.name));
      $("generate-strategy").replaceChildren(...strategies.map(strategy => new Option(strategy.definition.strategy.name, strategy.strategy_id)));
      $("proposal-strategy").replaceChildren(new Option("All strategies", ""), ...strategies.map(strategy => new Option(strategy.definition.strategy.name, strategy.strategy_id)), new Option("Manual trades", "manual"), new Option("Portfolio stops", "portfolio_stop"));
      const positional = (strategyData.strategies || []).find(strategy => strategy.strategy_id === "positional_trend_following");
      if (positional) $("generate-strategy").value = positional.strategy_id;
      if (!data.accounts?.length) { $("actions-error").textContent = "Create a portfolio account on Home before reviewing actions."; return; }
      $("account").onchange = async () => { request?.abort(); ++generation; await dates(); await load(); };
      $("load-actions").onclick = load; $("check-stops").onclick = load; $("action-date").onchange = load; $("manual-action").onclick = manual;
      $("proposal-strategy").onchange = load;
      $("generate-actions").onclick = generate;
      $("start-action-worker").onclick = async () => {
        try { const result = await Screener.api("/api/operations/worker/start", {method:"POST"}); $("start-action-worker").hidden = true; $("generation-status").textContent = result.running ? "Worker started. Waiting for the proposal job to finish…" : "Worker start requested."; }
        catch (error) { $("generation-status").textContent = error.message; }
      };
      await dates(); await load();
    } catch (error) { $("actions-error").textContent = error.message; }
  });
  window.addEventListener("pagehide", () => { request?.abort(); clearInterval(generationPoll); });
})();
