(() => {
  const $ = id => document.getElementById(id);
  let request, generation = 0;
  function control(label, action) {
    const button = document.createElement("button");
    button.textContent = label; button.className = "secondary";
    button.onclick = async () => {button.disabled = true; try {await action();} catch(error) {$("actions-error").textContent = error.message;} finally {button.disabled = false;}};
    return button;
  }
  async function dates() {
    const account = $("account").value;
    if (!account) return;
    const data = await Screener.api("/api/v2/actions/proposals/dates?account_id=" + encodeURIComponent(account));
    $("action-date").replaceChildren(new Option("All dates", ""), ...data.action_dates.map(day => new Option(day, day)));
  }
  async function load() {
    request?.abort(); request = new AbortController(); const token = ++generation;
    const account = $("account").value; if (!account) return;
    const query = new URLSearchParams({account_id: account});
    if ($("action-date").value) query.set("action_date", $("action-date").value);
    try {
      const [data, risk] = await Promise.all([
        Screener.api("/api/v2/actions/proposals?" + query, {signal:request.signal}),
        Screener.api("/api/v2/actions/risk?account_id=" + encodeURIComponent(account), {signal:request.signal})
      ]);
      if (token !== generation || account !== $("account").value) return;
      $("proposals").replaceChildren(...data.proposals.map(proposal => {
        const review = document.createElement("div");
        if (proposal.status === "PENDING") {
          for (const action of ["approve", "reject"]) review.append(control(action, async () => {
            await Screener.api("/api/v2/actions/proposals/" + encodeURIComponent(proposal.proposal_id) + "/" + action, {method:"POST"}); await load();
          }));
        }
        if (proposal.status === "APPROVED") {
          if (proposal.strategy_id === "manual") review.append(control("Confirm manual fills", async () => {
            if (!confirm("Confirm that these quantities and prices were actually executed?")) return;
            await Screener.api("/api/v2/actions/proposals/" + encodeURIComponent(proposal.proposal_id) + "/process", {method:"POST"}); await load();
          }));
          review.append(control("Prepare broker intents (no submission)", async () => {
            const result = await Screener.api("/api/v2/portfolio/proposals/" + encodeURIComponent(proposal.proposal_id) + "/broker-intents", {method:"POST"});
            $("risk").textContent = JSON.stringify(result, null, 2);
          }));
        }
        return Screener.row([
          proposal.decisions.map(item => item.type + " " + (item.symbol || item.instrument_id || "") + " " + (item.units || "")).join("\n"),
          proposal.decisions.map(item => item.reason || "").join("\n"),
          proposal.action_date, proposal.status, review
        ]);
      }));
      $("risk").textContent = JSON.stringify(risk.projections, null, 2);
      $("actions-error").textContent = "";
    } catch(error) {if (error.name !== "AbortError" && token === generation) $("actions-error").textContent = error.message;}
  }
  function manual() {
    const modal = $("app-modal"), host = $("modal-content"); host.replaceChildren();
    const title = document.createElement("h2"); title.id = "modal-title"; title.textContent = "Manual transaction intent";
    const form = document.createElement("form"), fields = {};
    for (const [key, label, type] of [["date","Execution date","date"],["symbol","NSE symbol","text"],["units","Whole units","number"],["price","Actual unit price","number"],["reason","Reason / execution evidence","text"]]) {
      const field = document.createElement("label"), input = document.createElement("input"); field.textContent = label;
      input.type = type; input.required = true; if (type === "number") {input.min = "0"; input.step = key === "units" ? "1" : "0.01";}
      field.append(input); form.append(field); fields[key] = input;
    }
    const side = document.createElement("select"); side.setAttribute("aria-label","Side"); side.append(new Option("BUY","BUY"),new Option("SELL","SELL")); form.append(side);
    const submit = document.createElement("button"); submit.type = "submit"; submit.textContent = "Create reviewable intent"; form.append(submit);
    form.onsubmit = async event => {
      event.preventDefault(); submit.disabled = true;
      try {await Screener.api("/api/v2/actions/manual",{method:"POST",body:JSON.stringify({
        account_id:$("account").value, action_date:fields.date.value, reason:fields.reason.value,
        entries:[{symbol:fields.symbol.value.trim().toUpperCase(),exchange:"NSE",side:side.value,units:Number(fields.units.value),price:fields.price.value}]
      })}); modal.close(); await dates(); await load();}
      catch(error) {$("actions-error").textContent = error.message;} finally {submit.disabled = false;}
    };
    host.append(title,form); modal.showModal(); fields.date.focus();
  }
  document.addEventListener("DOMContentLoaded", async () => {
    try {
      const data = await Screener.api("/api/v2/portfolio/accounts");
      $("account").replaceChildren(...data.accounts.map(account => new Option(account.account_id,account.account_id)));
      $("account").onchange = async () => {request?.abort(); ++generation; await dates(); await load();};
      $("load-actions").onclick = load; $("action-date").onchange = load; $("manual-action").onclick = manual;
      await dates(); await load();
    } catch(error) {$("actions-error").textContent = error.message;}
  });
  window.addEventListener("pagehide", () => request?.abort());
})();
