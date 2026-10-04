(() => {
  let stream = null;
  let generation = 0;
  const $ = id => document.getElementById(id);
  const fmt = value => value == null ? "—" : `₹${Number(value).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  const today = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}`; };

  function drawChart(id, rows, field, color, negative = false) {
    const svg = $(id); svg.replaceChildren();
    const values = rows.map(row => Number(row[field])).filter(Number.isFinite);
    if (!values.length) return;
    const left = 12, right = 588, top = 12, bottom = 164;
    const high = negative ? 0 : Math.max(...values);
    const low = negative ? Math.min(...values, -0.01) : Math.min(...values);
    const span = high - low || 1;
    const zeroY = bottom - ((0 - low) / span) * (bottom - top);
    const points = values.map((value, index) => {
      const x = values.length === 1 ? (left + right) / 2 : left + index * (right - left) / (values.length - 1);
      const y = bottom - ((value - low) / span) * (bottom - top);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(" ");
    const baseline = document.createElementNS("http://www.w3.org/2000/svg", "line");
    baseline.setAttribute("x1", String(left)); baseline.setAttribute("x2", String(right)); baseline.setAttribute("y1", String(zeroY)); baseline.setAttribute("y2", String(zeroY)); baseline.setAttribute("stroke", "var(--line)"); baseline.setAttribute("stroke-dasharray", "4 5");
    const line = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
    line.setAttribute("points", points); line.setAttribute("fill", "none"); line.setAttribute("stroke", color); line.setAttribute("stroke-width", "3"); line.setAttribute("stroke-linejoin", "round"); line.setAttribute("stroke-linecap", "round");
    svg.append(baseline, line);
  }

  async function accounts() {
    const data = await Screener.api("/api/portfolio/accounts");
    const selected = $("account").value;
    $("account").replaceChildren(...data.accounts.map(account => new Option(account.account_id, account.account_id)));
    if (data.accounts.some(account => account.account_id === selected)) $("account").value = selected;
    $("live-toggle").disabled = !data.accounts.length;
    if (!data.accounts.length) $("home-error").textContent = "Create an account to start tracking a portfolio.";
  }

  function render(data) {
    Screener.text($("equity"), fmt(data.equity));
    Screener.text($("invested"), fmt(data.invested_cost));
    Screener.text($("cash"), fmt(data.cash));
    Screener.text($("unrealised"), fmt(data.unrealised_gain));
    Screener.text($("realised"), fmt(data.realised_pnl));
    Screener.text($("day-pnl"), fmt(data.day_pnl));
    Screener.text($("xirr"), data.xirr == null ? "Insufficient cash-flow history" : `${(Number(data.xirr) * 100).toFixed(2)}%`);
    Screener.text($("risk"), fmt(data.stop_based_risk));
    Screener.text($("stale-prices"), `${data.stale_prices ?? 0}`);
    $("price-freshness").textContent = data.holdings?.some(item => !item.fresh) ? "Some prices are from earlier sessions" : `Valued ${data.as_of_date}`;
    $("holdings").replaceChildren(...data.holdings.map(holding => {
      const costPerUnit = Number(holding.units) ? Number(holding.cost) / Number(holding.units) : null;
      const pnl = Number(holding.market_value) - Number(holding.cost);
      const pnlNode = document.createElement("span"); pnlNode.textContent = fmt(pnl); pnlNode.className = pnl >= 0 ? "positive" : "negative";
      return Screener.row([holding.symbol || holding.instrument_id, holding.acquisition_date, holding.units, fmt(costPerUnit), fmt(holding.price), fmt(holding.current_trailing_stop), fmt(holding.hard_stop), fmt(holding.cost), fmt(holding.market_value), pnlNode, holding.price_date]);
    }));
    if (!data.holdings.length) $("holdings").append(Screener.row(["No open holdings", "", "", "", "", "", "", "", "", "", ""]));
  }

  async function refresh() {
    const account = $("account").value;
    if (!account) return;
    const ownGeneration = ++generation;
    const asOf = $("as-of").value || today();
    try {
      const [value, history, journal] = await Promise.all([
        Screener.api(`/api/portfolio/accounts/${encodeURIComponent(account)}/valuation?as_of_date=${encodeURIComponent(asOf)}`),
        Screener.api(`/api/portfolio/accounts/${encodeURIComponent(account)}/valuation/history`),
        Screener.api(`/api/portfolio/accounts/${encodeURIComponent(account)}/journal`),
      ]);
      if (ownGeneration !== generation || account !== $("account").value) return;
      render(value);
      drawChart("equity-history-chart", history.history, "equity", "var(--accent)");
      drawChart("drawdown-history-chart", history.history, "drawdown", "var(--danger)", true);
      $("history").replaceChildren(...history.history.map(item => Screener.row([item.as_of_date, fmt(item.equity), `${(Number(item.drawdown)*100).toFixed(2)}%`])));
      $("journal").replaceChildren(...journal.journal.map(item => Screener.row([item.symbol || item.instrument_id, item.buy_date, item.sell_date, item.units, fmt(item.buy_price), fmt(item.sell_price), fmt(item.realised_pnl), item.holding_days])));
      if (!journal.journal.length) $("journal").append(Screener.row(["No closed trades yet", "", "", "", "", "", "", ""]));
      $("home-error").textContent = "";
    } catch (error) { if (ownGeneration === generation) $("home-error").textContent = error.message; }
  }

  function openForm(kind) {
    const modal = $("app-modal"), content = $("modal-content"); content.replaceChildren();
    const title = document.createElement("h2"); title.id = "modal-title";
    const note = document.createElement("p"); note.className = "muted";
    const fields = {};
    function addField(name, label, type = "text", value = "") {
      const wrapper = document.createElement("div"); wrapper.className = "field"; wrapper.style.margin = ".7rem 0";
      const caption = document.createElement("label"); caption.textContent = label;
      const input = document.createElement("input"); input.type = type; input.value = value; input.id = `portfolio-${name}`;
      if (type === "number") input.min = "0.01";
      wrapper.append(caption, input); content.append(wrapper); fields[name] = input;
    }
    const save = document.createElement("button"); save.textContent = "Save";
    const cancel = document.createElement("button"); cancel.className = "secondary"; cancel.style.marginLeft = ".5rem"; cancel.textContent = "Cancel"; cancel.onclick = () => modal.close();
    if (kind === "account") {
      title.textContent = "Create portfolio account"; note.textContent = "Start with an empty ledger and opening cash.";
      addField("id", "Account name", "text"); addField("amount", "Opening cash (₹)", "number");
      save.onclick = async () => { try { await Screener.api("/api/portfolio/accounts", { method: "POST", body: JSON.stringify({ account_id: fields.id.value.trim(), opening_cash: fields.amount.value }) }); modal.close(); await accounts(); await refresh(); } catch (error) { note.textContent = error.message; note.className = "error"; } };
    } else if (kind === "cash") {
      title.textContent = "Cash deposit or withdrawal"; note.textContent = "This records an external capital flow in the account ledger.";
      const direction = document.createElement("select"); direction.append(new Option("Deposit", "DEPOSIT"), new Option("Withdrawal", "WITHDRAW")); fields.direction = direction;
      const wrap = document.createElement("div"); wrap.className = "field"; const label = document.createElement("label"); label.textContent = "Type"; wrap.append(label, direction); content.append(wrap);
      addField("amount", "Amount (₹)", "number"); addField("reason", "Note", "text", "Manual capital event");
      save.onclick = async () => { try { const account = await Screener.api(`/api/portfolio/accounts/${encodeURIComponent($("account").value)}`); await Screener.api(`/api/portfolio/accounts/${encodeURIComponent(account.account_id)}/cash-transfers`, { method: "POST", body: JSON.stringify({ idempotency_key: Screener.id(), expected_version: account.version, direction: direction.value, amount: fields.amount.value, reason: fields.reason.value.trim() }) }); modal.close(); await refresh(); } catch (error) { note.textContent = error.message; note.className = "error"; } };
    } else {
      const side = kind === "buy" ? "BUY" : "SELL";
      title.textContent = `Manual ${kind}`; note.textContent = "The fill is appended to the ledger and cannot be edited after saving.";
      addField("symbol", "NSE symbol", "text"); addField("date", "Trade date", "date", $("as-of").value || today()); addField("units", "Units", "number"); addField("price", "Execution price (₹)", "number"); addField("fee", "Fees (₹)", "number", "0");
      save.onclick = async () => { try { const account = await Screener.api(`/api/portfolio/accounts/${encodeURIComponent($("account").value)}`); await Screener.api(`/api/portfolio/accounts/${encodeURIComponent(account.account_id)}/fills`, { method: "POST", body: JSON.stringify({ idempotency_key: Screener.id(), expected_version: account.version, fills: [{ symbol: fields.symbol.value.trim().toUpperCase(), exchange: "NSE", fill_date: fields.date.value, side, units: Number(fields.units.value), price: fields.price.value, fee: fields.fee.value || "0" }] }) }); modal.close(); await refresh(); } catch (error) { note.textContent = error.message; note.className = "error"; } };
    }
    content.prepend(title, note); content.append(save, cancel); modal.showModal();
  }

  function toggleLive() {
    if (stream) { stream.close(); stream = null; $("live-toggle").textContent = "Live ticker off"; return; }
    const account = $("account").value; if (!account) return;
    stream = new EventSource(`/api/portfolio/accounts/${encodeURIComponent(account)}/ticker/stream`);
    stream.addEventListener("portfolio-ticker", event => { const data = JSON.parse(event.data); if (data.account_id === $("account").value) Screener.text($("equity"), fmt(data.equity)); });
    stream.onerror = () => { stream?.close(); stream = null; $("live-toggle").textContent = "Live ticker off"; };
    $("live-toggle").textContent = "Live ticker on";
  }

  document.addEventListener("DOMContentLoaded", async () => {
    $("as-of").value = today(); $("refresh-home").onclick = refresh;
    $("account").onchange = () => { stream?.close(); stream = null; $("live-toggle").textContent = "Live ticker off"; refresh(); };
    $("live-toggle").onclick = toggleLive; $("add-account").onclick = () => openForm("account");
    $("manual-buy").onclick = () => openForm("buy"); $("manual-sell").onclick = () => openForm("sell"); $("capital-event").onclick = () => openForm("cash");
    $("as-of").onchange = refresh;
    try { await accounts(); await refresh(); } catch (error) { $("home-error").textContent = error.message; }
  });
  window.addEventListener("pagehide", () => stream?.close());
})();
