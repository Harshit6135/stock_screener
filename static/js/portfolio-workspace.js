(() => {
  let stream = null;
  let streamAccount = null, liveGeneration = 0, viewData = null, intradayRows = [], lastChartTime = null;
  let generation = 0;
  let savedBrokerAccountId = null;
  const $ = id => document.getElementById(id);
  const fmt = value => value == null ? "—" : `₹${Number(value).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  const today = () => { return new Intl.DateTimeFormat("en-CA",{timeZone:"Asia/Kolkata",year:"numeric",month:"2-digit",day:"2-digit"}).format(new Date()); };

  function drawChart(id, rows, field, color, negative = false) {
    const svg = $(id); svg.replaceChildren();
    rows = rows.filter(row => row[field] != null && Number.isFinite(Number(row[field])));
    const values = rows.map(row => Number(row[field]));
    if (!values.length) { const label = document.createElementNS("http://www.w3.org/2000/svg", "text"); label.setAttribute("x", "12"); label.setAttribute("y", "90"); label.setAttribute("fill", "var(--muted)"); label.textContent = "No priced valuations available for this period."; svg.append(label); return; }
    const left = 12, right = 588, top = 24, bottom = 145;
    const high = negative ? 0 : Math.max(...values);
    const low = negative ? Math.min(...values, -0.01) : Math.min(...values);
    const span = high - low || 1;
    const zeroY = bottom - ((0 - low) / span) * (bottom - top);
    const firstTime = Date.parse(rows[0].as_of_date), lastTime = Date.parse(rows[rows.length - 1].as_of_date);
    const points = values.map((value, index) => {
      const x = values.length === 1 ? (left + right) / 2 : lastTime > firstTime ? left + (Date.parse(rows[index].as_of_date) - firstTime) * (right - left) / (lastTime - firstTime) : left + index * (right - left) / (values.length - 1);
      const y = bottom - ((value - low) / span) * (bottom - top);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(" ");
    const baseline = document.createElementNS("http://www.w3.org/2000/svg", "line");
    baseline.setAttribute("x1", String(left)); baseline.setAttribute("x2", String(right)); baseline.setAttribute("y1", String(zeroY)); baseline.setAttribute("y2", String(zeroY)); baseline.setAttribute("stroke", "var(--line)"); baseline.setAttribute("stroke-dasharray", "4 5");
    const line = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
    line.setAttribute("points", points); line.setAttribute("fill", "none"); line.setAttribute("stroke", color); line.setAttribute("stroke-width", "3"); line.setAttribute("stroke-linejoin", "round"); line.setAttribute("stroke-linecap", "round");
    if (zeroY >= top && zeroY <= bottom) svg.append(baseline);
    svg.append(line);
    for (const [x, y, value, anchor] of [[left, 14, negative ? `${(high * 100).toFixed(1)}%` : fmt(high), "start"], [right, 158, negative ? `${(low * 100).toFixed(1)}%` : fmt(low), "end"], [left, 177, rows[0].as_of_date, "start"], [right, 177, rows[rows.length - 1].as_of_date, "end"]]) { const label = document.createElementNS("http://www.w3.org/2000/svg", "text"); label.setAttribute("x", x); label.setAttribute("y", y); label.setAttribute("text-anchor", anchor); label.setAttribute("fill", "var(--muted)"); label.setAttribute("font-size", "11"); label.textContent = typeof value === "string" && value.includes("T") ? new Date(value).toLocaleTimeString("en-IN",{timeZone:"Asia/Kolkata",hour:"2-digit",minute:"2-digit",hour12:false}) : value; svg.append(label); }
    values.forEach((value, index) => { const dot = document.createElementNS("http://www.w3.org/2000/svg", "circle"); const [x, y] = points.split(" ")[index].split(","); dot.setAttribute("cx", x); dot.setAttribute("cy", y); dot.setAttribute("r", values.length === 1 ? "4" : "2"); dot.setAttribute("fill", color); const title = document.createElementNS("http://www.w3.org/2000/svg", "title"); title.textContent = `${rows[index].as_of_date}: ${negative ? `${(value * 100).toFixed(2)}%` : fmt(value)}`; dot.append(title); svg.append(dot); });
  }

  async function accounts() {
    const data = await Screener.api("/api/portfolio/accounts");
    const selected = $("account").value;
    $("account").replaceChildren(...data.accounts.map(account => new Option(account.display_name || account.account_id, account.account_id)));
    if (data.accounts.some(account => account.account_id === selected)) $("account").value = selected;
    $("live-toggle").disabled = !data.accounts.length;
    $("connect-kite").disabled = !data.accounts.length;
    $("edit-account").disabled = !data.accounts.length; $("refresh-credentials").disabled = !data.accounts.length;
    $("upload-tradebook").disabled = !data.accounts.length;
    await brokerStatus();
    if (!data.accounts.length) $("home-error").textContent = "Create an account to start tracking a portfolio.";
  }

  async function brokerStatus() {
    const selected = $("account").value;
    const data = await Screener.api("/api/broker-accounts");
    const broker = data.accounts.find(item => item.broker_account_id === selected);
    if (selected !== $("account").value) return;
    savedBrokerAccountId = broker ? selected : null;
    $("import-kite").disabled = !broker || broker.session_status !== "ACTIVE";
    $("portfolio-kite-status").textContent = broker ? `Portfolio Kite: ${broker.session_status === "ACTIVE" ? "saved session (validate before import)" : "login required"}` : "Portfolio Kite not connected";
  }

  async function refreshBroker() {
    const accountId = $("account").value;
    if (!accountId) return;
    $("refresh-home").disabled = true; $("import-kite").disabled = true;
    try {
      if (savedBrokerAccountId === accountId) {
        const preview = await Screener.api(`/api/broker-accounts/${encodeURIComponent(accountId)}/import-preview`);
        if (!preview.import_complete && !preview.history_mode) { showImportPreview(accountId, preview); return; }
        const result = await Screener.api(`/api/broker-accounts/${encodeURIComponent(accountId)}/import-holdings`, { method: "POST" });
        Screener.status(result.imported_positions ? `Imported ${result.imported_positions} Kite holdings; ${fmt(result.cash_deducted)} deducted from cash.` : `Updated prices for ${result.holding_count} Kite holdings.`);
        if (result.quantity_mismatches?.length) $("home-error").textContent = `Broker quantities differ for ${result.quantity_mismatches.join(", ")}. Upload the latest tradebook to update transactions.`;
      }
      await refresh();
    } catch (error) { $("home-error").textContent = error.message; }
    finally { $("refresh-home").disabled = false; await brokerStatus().catch(() => {}); }
  }

  async function previewImport() {
    const accountId = $("account").value;
    if (!accountId) return;
    $("import-kite").disabled = true;
    try {
      const preview = await Screener.api(`/api/broker-accounts/${encodeURIComponent(accountId)}/import-preview`);
      showImportPreview(accountId, preview);
    } catch (error) { $("home-error").textContent = error.message; }
    finally { await brokerStatus().catch(() => {}); }
  }

  function showImportPreview(accountId, preview, selectedIds = []) {
    const modal = $("app-modal"), content = $("modal-content"); content.replaceChildren();
    const title = document.createElement("h2"); title.id = "modal-title"; title.textContent = `Select Kite holdings · ${accountId}`;
    const note = document.createElement("p"); note.className = "muted";
    note.textContent = "Check holdings to import. Their acquisition cost is deducted from available cash once. Unchecked holdings stay ignored on refresh. Already imported holdings remain in ledger history. Older purchase dates are unknown.";
    note.textContent += " For realized gains and returns from your opening date, import full tradebook history first.";
    if (preview.history_mode) { note.textContent = "Select missing Kite holdings to import their current quantity and average cost directly. Purchase dates are requested next. Existing trade history stays intact; the snapshot adds no prior sells. Cost is deducted from cash once."; }
    content.append(title, note);
    const table = document.createElement("table"), head = document.createElement("thead"), body = document.createElement("tbody");
    head.append(Screener.row(["Import", "Symbol", "Broker exchange", "Units", "Average cost", "Price", "Status"]));
    const inputs = [];
    for (const holding of preview.holdings) {
      const checkbox = document.createElement("input"); checkbox.type = "checkbox"; checkbox.checked = holding.imported || selectedIds.includes(holding.instrument_id); checkbox.disabled = holding.imported;
      if (holding.eligible === false) { checkbox.checked = false; checkbox.disabled = true; }
      checkbox.setAttribute("aria-label", `Import ${holding.broker_symbol}`); inputs.push({ checkbox, holding });
      body.append(Screener.row([checkbox, holding.broker_symbol, holding.broker_exchange, holding.units, fmt(holding.unit_cost), fmt(holding.price), holding.reason || (holding.imported ? "Already recorded" : holding.purchase_date_known ? "Today's purchase" : "Available for direct import")]));
    }
    table.append(head, body); const wrap = document.createElement("div"); wrap.className = "table-wrap"; wrap.append(table); content.append(wrap);
    const summary = document.createElement("p"); content.append(summary);
    const selectAll = document.createElement("button"); selectAll.textContent = "Select all"; selectAll.className = "secondary";
    const ignoreAll = document.createElement("button"); ignoreAll.textContent = "Ignore remaining"; ignoreAll.className = "secondary";
    const save = document.createElement("button");
    const update = () => {
      const checked = inputs.filter(item => item.checkbox.checked);
      const added = checked.filter(item => !item.holding.imported).length;
      const cost = checked.filter(item => !item.holding.imported).reduce((total, item) => total + Number(item.holding.unit_cost) * item.holding.units, 0);
      summary.textContent = `${added} to import · ${checked.length - added} already imported · ${inputs.length - checked.length} ignored. Cost: ${fmt(cost)}. Cash after import: ${fmt(Number(preview.available_cash) - cost)}.`;
      save.textContent = added ? `Import ${added} selected` : "Save selection";
      if (preview.history_mode && !added) save.textContent = "Refresh recorded holding prices";
    };
    inputs.forEach(item => { item.checkbox.onchange = update; });
    selectAll.onclick = () => { inputs.forEach(item => { if (!item.checkbox.disabled) item.checkbox.checked = true; }); update(); };
    ignoreAll.onclick = () => { inputs.forEach(item => { if (!item.checkbox.disabled) item.checkbox.checked = false; }); update(); };
    save.onclick = async () => {
      save.disabled = true;
      try {
        const selected = inputs.filter(item => item.checkbox.checked).map(item => item.holding.instrument_id);
        if (inputs.some(item => item.checkbox.checked && !item.holding.imported)) { showPurchaseDates(accountId, preview, selected); return; }
        const result = await Screener.api(`/api/broker-accounts/${encodeURIComponent(accountId)}/import-holdings`, { method: "POST", body: JSON.stringify({ selected_instrument_ids: selected }) });
        modal.close(); content.replaceChildren(); await refresh();
        Screener.status(`Imported ${result.imported_positions} holdings; ${result.ignored_count} ignored; ${fmt(result.cash_deducted)} deducted from cash.`);
      } catch (error) { note.textContent = error.message; note.className = "error"; save.disabled = false; }
    };
    const cancel = document.createElement("button"); cancel.textContent = "Cancel"; cancel.className = "secondary"; cancel.onclick = () => { modal.close(); content.replaceChildren(); };
    content.append(selectAll, ignoreAll, save, cancel);
    update(); modal.showModal();
  }

  function showPurchaseDates(accountId, preview, selectedIds) {
    const modal = $("app-modal"), content = $("modal-content"); content.replaceChildren();
    const title = document.createElement("h2"); title.id = "modal-title"; title.textContent = "Purchase dates for selected holdings";
    const note = document.createElement("p"); note.className = "muted"; note.textContent = "Enter the actual purchase date for each stock. The import uses Kite's current quantity and average cost; your recorded trades stay intact.";
    content.append(title, note);
    const fields = [];
    for (const holding of preview.holdings.filter(row => selectedIds.includes(row.instrument_id) && !row.imported)) {
      const wrap = document.createElement("div"); wrap.className = "field";
      const label = document.createElement("label"); label.textContent = `${holding.broker_symbol} · ${holding.units} units · ${fmt(Number(holding.unit_cost) * holding.units)}`;
      const input = document.createElement("input"); input.type = "date"; input.required = true; input.min = preview.opening_date || ""; input.max = preview.observed_at.slice(0, 10); input.setAttribute("aria-label", `Purchase date for ${holding.broker_symbol}`);
      if (holding.purchase_date_known) input.value = input.max;
      label.append(input); wrap.append(label); content.append(wrap); fields.push({holding, input});
    }
    const save = document.createElement("button"); save.textContent = "Confirm dates & import";
    save.onclick = async () => {
      save.disabled = true;
      try {
        const dates = {};
        for (const {holding, input} of fields) {
          if (!input.value || !input.checkValidity()) { input.reportValidity(); throw new Error(`Enter a purchase date for ${holding.broker_symbol} between account opening and today.`); }
          dates[holding.instrument_id] = input.value;
        }
        const result = await Screener.api(`/api/broker-accounts/${encodeURIComponent(accountId)}/import-holdings`, {method: "POST", body: JSON.stringify({selected_instrument_ids: selectedIds, purchase_dates: dates})});
        modal.close(); content.replaceChildren(); await refresh();
        Screener.status(`Imported ${result.imported_positions} Kite holdings; ${fmt(result.cash_deducted)} deducted from cash.`);
      } catch (error) { note.textContent = error.message; note.className = "error"; save.disabled = false; }
    };
    const back = document.createElement("button"); back.textContent = "Back to stock selection"; back.className = "secondary"; back.onclick = () => showImportPreview(accountId, preview, selectedIds);
    const cancel = document.createElement("button"); cancel.textContent = "Cancel"; cancel.className = "secondary"; cancel.onclick = () => {modal.close(); content.replaceChildren();};
    content.append(save, back, cancel);
  }

  function uploadTradebook() {
    const accountId = $("account").value; if (!accountId) return;
    const modal = $("app-modal"), content = $("modal-content"); content.replaceChildren();
    const title = document.createElement("h2"); title.id = "modal-title"; title.textContent = `Import tradebook history · ${accountId}`;
    const note = document.createElement("p"); note.className = "muted";
    note.textContent = "Choose the full Equity tradebook from Zerodha Console. Review all buys and sells, including closed positions, before applying. Each selected symbol imports its complete history.";
    const mode = document.createElement("select"); mode.setAttribute("aria-label", "Tradebook import mode"); mode.append(new Option("Full history — buys and sells", "history"), new Option("Recover open-lot dates only", "open_lots"));
    const file = document.createElement("input"); file.type = "file"; file.accept = ".csv,text/csv"; file.setAttribute("aria-label", "Tradebook CSV");
    const previewButton = document.createElement("button"); previewButton.textContent = "Preview trades";
    const results = document.createElement("div");
    const cancel = document.createElement("button"); cancel.textContent = "Cancel"; cancel.className = "secondary"; cancel.onclick = () => { modal.close(); content.replaceChildren(); };
    previewButton.onclick = async () => {
      previewButton.disabled = true; results.replaceChildren();
      try {
        if (!file.files[0]) throw new Error("Choose a tradebook CSV file.");
        const data = new FormData(); data.append("file", file.files[0]); data.append("mode", mode.value);
        const response = await fetch(`/api/portfolio/accounts/${encodeURIComponent(accountId)}/tradebook/preview`, { method: "POST", body: data });
        const preview = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(preview.error || "Tradebook upload failed.");
        renderPreview(preview);
      } catch (error) { note.textContent = error.message; note.className = "error"; }
      finally { previewButton.disabled = false; }
    };
    const renderPreview = (preview) => {
        results.replaceChildren();
        const fullHistory = preview.mode === "history";
        note.textContent = fullHistory ? `${preview.trade_count} trades read · ${preview.closed_symbols} closed symbols included · ${preview.duplicate_rows} duplicate rows skipped. Select every symbol for complete portfolio returns.` : `${preview.trade_count} trades read · ${preview.closed_symbols} fully closed symbols excluded · ${preview.ignored_open_symbols} open symbols outside this portfolio ignored · ${preview.duplicate_rows} duplicate rows skipped.`;
        note.className = "muted";
        if (fullHistory) {
          const info = document.createElement("p"); info.className = "notice";
          info.textContent = preview.fees_provided ? "Imported charges are included in cash and realized gain." : "This CSV has no charges column. Gains exclude brokerage and taxes; upload charges with a supported fees/charges column to include them.";
          results.append(info);
          if (preview.summary) { const overview = document.createElement("p"); overview.textContent = `All trades: opening ${preview.summary.opening_date} with ${fmt(preview.summary.initial_balance)} · cash ${fmt(preview.summary.cash)} · realized gain ${fmt(preview.summary.realised_pnl)}.`; results.append(overview);
            if (Number(preview.summary.minimum_cash) < 0) { const deficit = document.createElement("p"); deficit.className = "notice"; deficit.textContent = `History shows a temporary cash deficit of ${fmt(-Number(preview.summary.minimum_cash))}. No extra deposit will be invented; record any actual funding separately.`; results.append(deficit); }
          }
          if (preview.blocked_reason) { const blocked = document.createElement("p"); blocked.className = "error"; blocked.textContent = preview.blocked_reason; results.append(blocked); }
        }
        for (const warning of preview.corporate_action_warnings || []) {
          const detail = document.createElement("p"); detail.className = "notice"; detail.textContent = warning; results.append(detail);
        }
        for (const adjustment of preview.corporate_action_adjustments || []) {
          const detail = document.createElement("p"); detail.className = "notice";
          const bonus = adjustment.action_type === "BONUS";
          detail.textContent = `${adjustment.symbol}: ${bonus ? `${adjustment.numerator - adjustment.denominator}-for-${adjustment.denominator} bonus` : `${adjustment.numerator}-for-${adjustment.denominator} split`} on ${adjustment.effective_date}; ${adjustment.units_before} shares became ${adjustment.units_after}, with total acquisition cost preserved. ${adjustment.date_note || ""} `;
          const source = document.createElement("a"); source.textContent = "Corporate-action source"; source.href = adjustment.source_url; source.target = "_blank"; source.rel = "noopener noreferrer";
          detail.append(source); results.append(detail);
        }
        for (const problem of preview.unresolved_symbols || []) {
          const warning = document.createElement("p"); warning.className = "notice"; warning.textContent = `${problem.reason}. This symbol is excluded until resolved; other matching holdings can still be applied.`;
          results.append(warning);
        }
        const table = document.createElement("table"), head = document.createElement("thead"), body = document.createElement("tbody"), selections = [];
        head.append(Screener.row(fullHistory ? ["Import", "Symbol", "Buys", "Sells", "Open units", "Status"] : ["Apply", "Symbol", "Portfolio units", "CSV open units", "Remaining buy lots", "Status"]));
        for (const holding of preview.holdings) {
          const input = document.createElement("input"); input.type = "checkbox"; input.checked = holding.eligible; input.disabled = !holding.eligible;
          input.setAttribute("aria-label", `Apply tradebook dates for ${holding.symbol}`); selections.push({ input, holding });
          const lots = document.createElement("span"); lots.style.whiteSpace = "pre-line";
          lots.textContent = holding.lots.map(lot => `${lot.date} · ${lot.units} units @ ${fmt(lot.unit_cost)}`).join("\n") || "—";
          body.append(Screener.row(fullHistory ? [input, holding.symbol, holding.buy_count, holding.sell_count, holding.csv_units, holding.reason] : [input, holding.symbol, holding.portfolio_units, holding.csv_units, lots, holding.reason]));
        }
        table.append(head, body); const wrap = document.createElement("div"); wrap.className = "table-wrap"; wrap.append(table); results.append(wrap);
        const summary = document.createElement("p"), apply = document.createElement("button"); apply.textContent = fullHistory ? "Import selected trade history" : "Apply selected open lots";
        const update = () => { const selected = selections.filter(item => item.input.checked); apply.disabled = !selected.length || !!preview.blocked_reason; summary.textContent = fullHistory ? `${selected.length} symbols selected · ${selected.reduce((total, item) => total + item.holding.trade_count, 0)} trades. Buys deduct cash; sells credit cash and record FIFO realized gain. Repeated trades are skipped.` : `${selected.length} holdings selected. Cash correction: ${fmt(selected.reduce((total, item) => total + Number(item.holding.cash_adjustment || 0), 0))}. Closed trades and their realised P&L will not be added.`; };
        selections.forEach(item => { item.input.onchange = update; }); update();
        apply.onclick = async () => {
          apply.disabled = true;
          try {
            const result = await Screener.api(`/api/portfolio/accounts/${encodeURIComponent(accountId)}/tradebook/apply`, { method: "POST", body: JSON.stringify({ upload_id: preview.upload_id, expected_version: preview.expected_version, mode: fullHistory ? "history" : "open_lots", selected_instrument_ids: selections.filter(item => item.input.checked).map(item => item.holding.instrument_id) }) });
            modal.close(); content.replaceChildren(); await refresh(); Screener.status(fullHistory ? `Imported ${result.imported_trades} trades; ${result.duplicate_trades} duplicates skipped; realized gain ${fmt(result.realised_pnl)}.` : `Updated ${result.updated_holdings} holdings with ${result.open_lots} dated open lots.`);
          } catch (error) {
            if (error.message === "preview this tradebook again to resolve corporate actions from exchange records") {
              try {
                const refreshed = await Screener.api(`/api/portfolio/accounts/${encodeURIComponent(accountId)}/tradebook/refresh-preview`, { method: "POST", body: JSON.stringify({ upload_id: preview.upload_id, mode: fullHistory ? "history" : "open_lots" }) });
                renderPreview(refreshed);
                note.textContent = "Corporate actions refreshed from exchange records. Review your selections and click import again.";
                note.className = "notice";
              } catch (refreshError) { note.textContent = refreshError.message; note.className = "error"; update(); }
            } else { note.textContent = error.message; note.className = "error"; update(); }
          }
        };
        results.append(summary, apply);
    };
    file.onchange = () => results.replaceChildren(); mode.onchange = () => results.replaceChildren();
    content.append(title, note, mode, file, previewButton, results, cancel); modal.showModal();
  }

  function connectKite() {
    const accountId = $("account").value;
    if (!accountId) return;
    const modal = $("app-modal"), content = $("modal-content");
    content.replaceChildren();
    const title = document.createElement("h2"); title.id = "modal-title"; title.textContent = `Connect portfolio Kite · ${accountId}`;
    const note = document.createElement("p"); note.className = "muted";
    note.textContent = "Enter this portfolio's Kite API key and secret, then sign in to Kite. The app obtains and saves the access token automatically. Set your Kite app's redirect URL to http://127.0.0.1:5000/integrations/kite/portfolio/callback.";
    content.append(title, note);
    if (savedBrokerAccountId === accountId) {
      const loginAgain = document.createElement("button"); loginAgain.textContent = "Log in with saved credentials";
      loginAgain.onclick = async () => {
        loginAgain.disabled = true;
        try {
          const login = await Screener.api(`/api/broker-accounts/${encodeURIComponent(accountId)}/authorize`, { method: "POST" });
          content.replaceChildren(); modal.close(); window.location.assign(login.authorization_url);
        } catch (error) { note.textContent = error.message; note.className = "error"; loginAgain.disabled = false; }
      };
      content.append(loginAgain);
    }
    const fields = {};
    for (const [key, label] of [["api_key", "Portfolio API key"], ["api_secret", "Portfolio API secret"]]) {
      const wrap = document.createElement("div"); wrap.className = "field"; wrap.style.margin = ".7rem 0";
      const caption = document.createElement("label"); caption.textContent = label; caption.htmlFor = `kite-${key}`;
      const input = document.createElement("input"); input.id = `kite-${key}`; input.type = "password"; input.autocomplete = "off";
      fields[key] = input; wrap.append(caption, input); content.append(wrap);
    }
    const save = document.createElement("button"); save.textContent = "Save and log in to Kite";
    const cancel = document.createElement("button"); cancel.textContent = "Cancel"; cancel.className = "secondary"; cancel.onclick = () => { content.replaceChildren(); modal.close(); };
    save.onclick = async () => {
      save.disabled = true;
      try {
        if (Object.values(fields).some(input => !input.value.trim())) throw new Error("Enter the portfolio API key and API secret.");
        await Screener.api("/api/broker-accounts", { method: "POST", body: JSON.stringify({ broker_account_id: accountId, account_name: accountId, api_key: fields.api_key.value.trim(), api_secret: fields.api_secret.value.trim() }) });
        const login = await Screener.api(`/api/broker-accounts/${encodeURIComponent(accountId)}/authorize`, { method: "POST" });
        content.replaceChildren(); modal.close(); window.location.assign(login.authorization_url);
      } catch (error) { note.textContent = error.message; note.className = "error"; }
      finally { save.disabled = false; }
    };
    content.append(save, cancel); modal.showModal();
  }

  function render(data) {
    viewData = data;
    Screener.text($("equity"), fmt(data.equity));
    Screener.text($("invested"), fmt(data.invested_cost));
    Screener.text($("cash"), fmt(data.cash));
    Screener.text($("unrealised"), fmt(data.unrealised_gain)); $("unrealised").classList.toggle("positive",Number(data.unrealised_gain)>=0); $("unrealised").classList.toggle("negative",Number(data.unrealised_gain)<0);
    Screener.text($("realised"), fmt(data.realised_pnl));
    Screener.text($("day-pnl"), fmt(data.day_pnl)); $("day-pnl").classList.toggle("positive",data.day_pnl!=null&&Number(data.day_pnl)>=0); $("day-pnl").classList.toggle("negative",data.day_pnl!=null&&Number(data.day_pnl)<0);
    Screener.text($("xirr"), data.xirr == null ? "Insufficient cash-flow history" : `${(Number(data.xirr) * 100).toFixed(2)}%`);
    Screener.text($("holdings-xirr"), data.holdings_xirr == null ? "Needs dated buys and prices" : `${(Number(data.holdings_xirr) * 100).toFixed(2)}%`);
    Screener.text($("realised-xirr"), data.realised_xirr == null ? "Needs dated closed trades" : `${(Number(data.realised_xirr) * 100).toFixed(2)}%`);
    Screener.text($("absolute-return"), data.total_return == null ? "Unavailable" : `${(Number(data.total_return) * 100).toFixed(2)}%`);
    Screener.text($("capital-risk"), fmt(data.capital_risk));
    Screener.text($("recorded-charges"), fmt(data.recorded_charges));
    Screener.text($("annualized-return"), data.annualized_return == null ? "Insufficient history or cash transfers" : `${(Number(data.annualized_return) * 100).toFixed(2)}%`);
    Screener.text($("net-gain"), fmt(data.net_gain));
    $("gain-note").textContent = [
      data.return_basis === "recorded_capital_and_cash_funded_purchases"
        ? "Returns use recorded opening capital, cash transfers, trades and cash-funded imports. Any unrecorded trades or bank transfers will change these figures."
        : "",
      data.fees_note || ""
    ].filter(Boolean).join(" ");
    Screener.text($("risk"), fmt(data.portfolio_risk));
    (data.tax_estimates || []).forEach((tax,index)=>{const key=index===0?"current":"previous";Screener.text($("tax-"+key+"-label"),`${tax.label} tax estimate`);Screener.text($("tax-"+key),fmt(tax.estimated_tax));Screener.text($("tax-"+key+"-detail"),`${tax.start_date} to ${tax.end_date} · Short-term gains ${fmt(tax.short_term_gains)} · Long-term gains ${fmt(tax.long_term_gains)} · Includes cess ${fmt(tax.cess)}`);});
    const riskDates = [...new Set(data.holdings.map(h => h.risk_date).filter(Boolean))].sort();
    $("risk-note").textContent = `ATR(14), 2× ATR stop, 3% lower hard stop; stops ratchet upward on completed daily bars${riskDates.length ? ` through ${riskDates[riskDates.length - 1]}` : ""}. Portfolio risk sums max(purchase cost − trailing stop value, 0) for each lot. Capital risk retains negative values when stops protect gains.${data.breached_stop_holdings ? ` ${data.breached_stop_holdings} holdings are already below a stop; zero distance is not a safe position.` : ""} Breaches create sell actions below; Approve & sell on Kite submits the reviewed order.`;
    Screener.text($("stale-prices"), `${data.stale_prices ?? 0}`);
    $("price-freshness").textContent = data.holdings?.some(item => !item.fresh) ? "Some prices are from earlier sessions" : `Valued ${data.as_of_date}`;
    renderHoldings(data.holdings);
    $("portfolio-alert").hidden = !data.breached_stop_holdings;
    $("portfolio-alert-text").textContent = `${data.breached_stop_holdings || 0} holding(s) need a stop review.`;
    for (const id of ["xirr", "holdings-xirr", "realised-xirr", "annualized-return"]) $(id).classList.toggle("metric-long", $(id).textContent.length > 15);

  }

  async function stopActions(account, token) {
    try {
      const result = await Screener.api("/api/actions/stops/check", {method:"POST", body:JSON.stringify({account_id:account})});
      if (token !== generation || account !== $("account").value) return;
      $("stop-actions-error").textContent = "";
      $("stop-actions").replaceChildren(...result.proposals.map(proposal => {
        const decision = proposal.decisions[0], order = proposal.broker_order;
        const review = document.createElement("div");
        function button(label, path) {
          const node = document.createElement("button"); node.type = "button"; node.textContent = label;
          node.onclick = async () => { node.disabled = true; try {
            const result = await Screener.api(path, {method:"POST", ...(path.endsWith("approve-execute") ? {body:JSON.stringify({approved:true})} : {})});
            await refresh();
            if (result.order) $("stop-actions-error").textContent = `Kite order ${result.order.broker_order_id || result.order.order_id}: ${result.order.status}${result.order.status === "SUBMITTED" ? " — awaiting confirmed fills" : ""}.`;
          } catch (error) { $("stop-actions-error").textContent = error.message; } finally { node.disabled = false; } };
          review.append(node);
        }
        const id = encodeURIComponent(proposal.proposal_id);
        if (["PENDING", "APPROVED"].includes(proposal.status) && (!order || order.status === "LOCAL_CREATED")) {
          button(proposal.status === "APPROVED" ? "Submit approved sell on Kite" : "Approve & sell on Kite", `/api/actions/stops/${id}/approve-execute`);
          if (proposal.status === "PENDING") button("Reject", `/api/actions/proposals/${id}/reject`);
        }
        if (order && !["FILLED", "CANCELLED", "REJECTED", "LOCAL_CREATED"].includes(order.status)) button("Refresh Kite order", `/api/actions/stops/${id}/reconcile`);
        return Screener.row([decision.symbol, decision.units, fmt(decision.stop_threshold), `${fmt(decision.execution_price)} (${decision.price_date})`, order?.status || proposal.status, review]);
      }));
      if (!result.proposals.length) $("stop-actions").append(Screener.row(["No breached holdings", "", "", "", "", ""]));
    } catch (error) { if (token === generation) $("stop-actions-error").textContent = error.message; }
  }

  async function refresh() {
    const account = $("account").value;
    if (!account) return;
    const ownGeneration = ++generation;
    const asOf = $("as-of").value || today();
    try {
      const [value, history, journal] = await Promise.all([
        Screener.api(`/api/portfolio/accounts/${encodeURIComponent(account)}/valuation?as_of_date=${encodeURIComponent(asOf)}`),
        Screener.api(`/api/portfolio/accounts/${encodeURIComponent(account)}/valuation/history?as_of_date=${encodeURIComponent(asOf)}&limit=500`),
        Screener.api(`/api/portfolio/accounts/${encodeURIComponent(account)}/journal`),
      ]);
      if (ownGeneration !== generation || account !== $("account").value) return;
      render(value);
      drawChart("equity-history-chart", history.history, "equity", "var(--accent)");
      drawChart("drawdown-history-chart", history.history, "drawdown", "var(--danger)", true);
      $("history-note").textContent = history.missing_price_days ? `${history.history.length} valuations reconstructed from trades and stored prices. ${history.missing_price_days} dates omitted because historical prices are missing${history.missing_symbols?.length ? ` for ${history.missing_symbols.slice(0, 5).join(", ")}${history.missing_symbols.length > 5 ? ` and ${history.missing_symbols.length - 5} others` : ""}` : ""}. Drawdown uses available valuations and adjusts for cash transfers.` : `${history.history.length} valuations reconstructed from trades and stored prices. Drawdown adjusts for cash transfers.`;
      $("history-note").title = history.missing_symbols?.length ? `Missing historical prices: ${history.missing_symbols.join(", ")}` : "";
      $("history").replaceChildren(...history.history.map(item => Screener.row([item.as_of_date, fmt(item.equity), `${(Number(item.drawdown)*100).toFixed(2)}%`])));
      $("journal").replaceChildren(...journal.journal.map(item => Screener.row([item.symbol || item.instrument_id, item.buy_date_end && item.buy_date_end !== item.buy_date ? `${item.buy_date} – ${item.buy_date_end}` : item.buy_date, item.sell_date, item.units, fmt(item.buy_price), fmt(item.sell_price), fmt(item.realised_pnl), item.holding_days_min != null && item.holding_days_min !== item.holding_days ? `${item.holding_days_min} – ${item.holding_days}` : item.holding_days])));
      if (!journal.journal.length) $("journal").append(Screener.row(["No closed trades yet", "", "", "", "", "", "", ""]));
      $("home-error").textContent = "";
      await stopActions(account, ownGeneration);
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
      caption.htmlFor = input.id;
      if (type === "number") { input.min = "0.01"; input.step = "any"; }
      wrapper.append(caption, input); content.append(wrapper); fields[name] = input;
    }
    const save = document.createElement("button"); save.textContent = "Save";
    const cancel = document.createElement("button"); cancel.className = "secondary"; cancel.style.marginLeft = ".5rem"; cancel.textContent = "Cancel"; cancel.onclick = () => modal.close();
    if (kind === "account") {
      title.textContent = "Create portfolio account"; note.textContent = "Set the date your initial capital was available. After Kite login, use Import tradebook history to reconstruct buys and sells.";
      addField("id", "Account name", "text");
      addField("opening_date", "Account opening date", "date", "2026-02-01"); fields.opening_date.max = today(); fields.opening_date.required = true;
      addField("amount", "Initial balance (₹)", "number", "300000");
      fields.amount.min = "0";
      addField("api_key", "Portfolio Kite API key", "text"); addField("api_secret", "Portfolio Kite API secret", "password");
      save.textContent = "Create and log in to Kite";
      let createdAccountId = null;
      save.onclick = async () => {
        save.disabled = true;
        try {
          const accountId = fields.id.value.trim();
          for (const [name, label] of [["id", "account name"], ["opening_date", "account opening date"], ["amount", "initial balance"], ["api_key", "Portfolio Kite API key"], ["api_secret", "Portfolio Kite API secret"]]) {
            if (!fields[name].value.trim()) { fields[name].focus(); throw new Error(`Enter ${label}.`); }
          }
          if (!fields.opening_date.checkValidity()) { fields.opening_date.focus(); throw new Error("Account opening date must be a valid date on or before today."); }
          if (!fields.amount.checkValidity()) { fields.amount.focus(); throw new Error("Initial balance must be a valid number, zero or greater."); }
          if (createdAccountId && createdAccountId !== accountId) throw new Error("This account was already created. Keep its name to retry Kite setup.");
          if (!createdAccountId) { await Screener.api("/api/portfolio/accounts", { method: "POST", body: JSON.stringify({ account_id: accountId, opening_cash: fields.amount.value, opening_date: fields.opening_date.value }) }); createdAccountId = accountId; }
          await Screener.api("/api/broker-accounts", { method: "POST", body: JSON.stringify({ broker_account_id: accountId, account_name: accountId, api_key: fields.api_key.value.trim(), api_secret: fields.api_secret.value.trim() }) });
          const login = await Screener.api(`/api/broker-accounts/${encodeURIComponent(accountId)}/authorize`, { method: "POST" });
          content.replaceChildren(); modal.close(); window.location.assign(login.authorization_url);
        } catch (error) { note.textContent = error.message; note.className = "error"; save.disabled = false; }
      };
    } else if (kind === "cash") {
      title.textContent = "Cash deposit or withdrawal"; note.textContent = "This records an external capital flow in the account ledger.";
      const direction = document.createElement("select"); direction.append(new Option("Deposit", "DEPOSIT"), new Option("Withdrawal", "WITHDRAW")); fields.direction = direction;
      const wrap = document.createElement("div"); wrap.className = "field"; const label = document.createElement("label"); label.textContent = "Type"; wrap.append(label, direction); content.append(wrap);
      addField("amount", "Amount (₹)", "number"); addField("reason", "Note", "text", "Manual capital event");
      addField("date", "Investment date", "date", today()); fields.date.required = true; fields.date.max = today();
      direction.onchange = () => { fields.date.previousElementSibling.textContent = direction.value === "DEPOSIT" ? "Investment date" : "Withdrawal date"; };
      note.textContent = "Record the date the money was invested or withdrawn. Dates are recorded in India time.";
      save.onclick = async () => { try { if (!fields.date.value || !fields.date.checkValidity()) throw new Error("Choose a valid date on or before today."); const account = await Screener.api(`/api/portfolio/accounts/${encodeURIComponent($("account").value)}`); await Screener.api(`/api/portfolio/accounts/${encodeURIComponent(account.account_id)}/cash-transfers`, { method: "POST", body: JSON.stringify({ idempotency_key: Screener.id(), expected_version: account.version, direction: direction.value, amount: fields.amount.value, reason: fields.reason.value.trim(), occurred_at: `${fields.date.value}T00:00:00+05:30` }) }); modal.close(); await refresh(); } catch (error) { note.textContent = error.message; note.className = "error"; } };
    } else {
      const side = kind === "buy" ? "BUY" : "SELL";
      title.textContent = `Manual ${kind}`; note.textContent = "The fill is appended to the ledger and cannot be edited after saving.";
      addField("symbol", "NSE symbol", "text"); addField("date", "Trade date", "date", $("as-of").value || today()); addField("units", "Units", "number"); addField("price", "Execution price (₹)", "number"); addField("fee", "Fees (₹)", "number", "0");
      fields.units.min = "1"; fields.units.step = "1"; fields.fee.min = "0";
      save.onclick = async () => { try { const account = await Screener.api(`/api/portfolio/accounts/${encodeURIComponent($("account").value)}`); await Screener.api(`/api/portfolio/accounts/${encodeURIComponent(account.account_id)}/fills`, { method: "POST", body: JSON.stringify({ idempotency_key: Screener.id(), expected_version: account.version, fills: [{ symbol: fields.symbol.value.trim().toUpperCase(), exchange: "NSE", fill_date: fields.date.value, side, units: Number(fields.units.value), price: fields.price.value, fee: fields.fee.value || "0" }] }) }); modal.close(); await refresh(); } catch (error) { note.textContent = error.message; note.className = "error"; } };
    }
    content.prepend(title, note); content.append(save, cancel); modal.showModal();
  }

  async function editAccount() {
    const id = $("account").value; if (!id) return;
    try {
      const detail = await Screener.api(`/api/portfolio/accounts/${encodeURIComponent(id)}`);
      const modal = $("app-modal"), host = $("modal-content"); host.replaceChildren();
      const title = document.createElement("h2"); title.textContent = "Edit portfolio account";
      const note = document.createElement("p"); note.className = "muted"; note.textContent = "Changing the opening date or initial balance recalculates performance. Leave replacement Kite credentials blank to keep the saved ones.";
      const form = document.createElement("form"), fields = {};
      for (const [key, label, type, value] of [["display_name","Account name","text",detail.display_name || id],["opening_date","Account opening date","date",detail.opening_date],["opening_cash","Initial balance (₹)","number",detail.opening_cash],["api_key","Replacement Kite API key","password",""],["api_secret","Replacement Kite API secret","password",""]]) {
        const field = document.createElement("label"); field.textContent = label;
        const input = document.createElement("input"); input.type = type; input.value = value; input.required = !key.startsWith("api_"); input.autocomplete = "off";
        if (type === "number") { input.min = "0"; input.step = "any"; }
        if (type === "date") input.max = today();
        field.append(input); form.append(field); fields[key] = input;
      }
      const error = document.createElement("p"); error.className = "error";
      const save = document.createElement("button"); save.type = "submit"; save.textContent = "Save account details";
      form.append(error, save);
      form.onsubmit = async event => { event.preventDefault(); save.disabled = true; try {
        if (Boolean(fields.api_key.value.trim()) !== Boolean(fields.api_secret.value.trim())) throw new Error("Enter both replacement API key and secret.");
        const current = await Screener.api(`/api/portfolio/accounts/${encodeURIComponent(id)}`);
        await Screener.api(`/api/portfolio/accounts/${encodeURIComponent(id)}`, {method:"PUT",body:JSON.stringify({display_name:fields.display_name.value.trim(), opening_date:fields.opening_date.value, opening_cash:fields.opening_cash.value, expected_version:current.version, expected_details_version:detail.details_version})});
        const broker = await Screener.api("/api/broker-accounts");
        if (broker.accounts.some(row => row.broker_account_id === id)) await Screener.api(`/api/broker-accounts/${encodeURIComponent(id)}`, {method:"PUT",body:JSON.stringify({account_name:fields.display_name.value.trim(), ...(fields.api_key.value.trim() ? {api_key:fields.api_key.value.trim(), api_secret:fields.api_secret.value.trim()} : {})})});
        else if (fields.api_key.value.trim()) await Screener.api("/api/broker-accounts", {method:"POST",body:JSON.stringify({broker_account_id:id, account_name:fields.display_name.value.trim(), api_key:fields.api_key.value.trim(), api_secret:fields.api_secret.value.trim()})});
        modal.close(); host.replaceChildren(); await accounts(); $("account").value = id; await refresh();
      } catch (failure) { error.textContent = failure.message; } finally { save.disabled = false; } };
      host.append(title, note, form); modal.showModal();
    } catch (error) { $("home-error").textContent = error.message; }
  }

  const pct = n => `${n >= 0 ? "+" : ""}${n.toFixed(2)}%`;
  function valueNode(amount, percent = null) {
    const node = document.createElement("span"); node.textContent = fmt(amount);
    if (amount != null) node.className = Number(amount) >= 0 ? "positive" : "negative";
    if (percent != null) { const sub = document.createElement("small"); sub.className = "stock-name"; sub.textContent = pct(percent); node.append(sub); }
    return node;
  }
  function holdingValues(h) {
    const priced = h.price != null, units = Number(h.units), cost = Number(h.cost);
    const value = priced ? Number(h.price) * units : null;
    const pnl = value == null ? null : value - cost;
    const day = h.day_pnl != null ? Number(h.day_pnl) : priced && h.previous_close != null && h.fresh ? (Number(h.price) - Number(h.previous_close)) * units : null;
    const stop = h.current_trailing_stop == null ? null : Number(h.current_trailing_stop);
    const status = !priced || stop == null ? "unavailable" : Number(h.price) <= Number(h.hard_stop ?? stop*.97) ? "below_hard_stop" : Number(h.price) <= stop ? "below_trailing_stop" : "above_stop";
    const risk = stop != null ? cost-stop*units : null;
    return {value,pnl,day,status,risk,gainPct:pnl!=null&&cost>0?pnl/cost*100:null,dayPct:day!=null&&Number(h.previous_close)>0?day/(Number(h.previous_close)*units)*100:null};
  }
  function updateHoldingRow(row, h) {
    const v=holdingValues(h), average=Number(h.cost)/Number(h.units);
    const set=(key,value,tone=null)=>{const cell=row.querySelector(`[data-field="${key}"]`);cell.replaceChildren(value instanceof Node?value:document.createTextNode(value==null?"—":String(value)));cell.classList.remove("positive","negative","tile-positive","tile-negative");if(tone!=null)cell.classList.add(tone?"positive":"negative",tone?"tile-positive":"tile-negative");};
    set("price",fmt(h.price),h.price==null?null:Number(h.price)>=average);
    set("stop",fmt(h.current_trailing_stop),h.current_trailing_stop==null?null:Number(h.current_trailing_stop)>=average);
    set("hard",fmt(h.hard_stop),h.hard_stop==null?null:Number(h.hard_stop)>=average);
    set("risk",fmt(v.risk),v.risk==null?null:v.risk<=0);
    set("value",fmt(v.value));set("gain",fmt(v.pnl),v.pnl==null?null:v.pnl>=0);
    set("gain-pct",v.gainPct==null?null:pct(v.gainPct),v.gainPct==null?null:v.gainPct>=0);
    set("day",fmt(v.day),v.day==null?null:v.day>=0);
    const detail=row.querySelector("button");detail.classList.toggle("stop-breached",v.status.startsWith("below_"));
    detail.textContent=v.status.startsWith("below_")?"Stop breached · Details":"Details";
    detail.title=`${h.quote_time?new Date(h.quote_time).toLocaleString("en-IN",{timeZone:"Asia/Kolkata"}):h.price_date||"No quote"} · ${h.price_basis||"No price source"}`;
  }
  function renderHoldings(holdings) {
    $("holdings").replaceChildren(...holdings.map((h,index)=>{
      const detail=document.createElement("button");detail.className="secondary";detail.onclick=()=>holdingDetail(h);
      const row=Screener.row([h.symbol||h.instrument_id,h.purchase_date_known===false?"Unknown":h.acquisition_date,h.units,fmt(Number(h.cost)/Number(h.units)),"","","","",fmt(h.cost),"","","","",detail]);
      row.dataset.instrument=h.instrument_id;row.dataset.holdingIndex=String(index);
      ["price","stop","hard","risk","value","gain","gain-pct","day"].forEach((key,i)=>row.cells[[4,5,6,7,9,10,11,12][i]].dataset.field=key);
      updateHoldingRow(row,h);return row;
    }));
    if(!holdings.length){const row=Screener.row(["No holdings yet. Import your portfolio or record an executed trade to get started."]);row.firstChild.colSpan=14;$("holdings").append(row);}
    filterHoldings();updateHoldingTotals();
  }
  function holdingDetail(h) {
    const modal=$("app-modal"),content=$("modal-content");content.replaceChildren();const title=document.createElement("h2");title.id="modal-title";title.textContent=h.symbol||h.instrument_id;content.append(title);
    const v=holdingValues(h);
    for(const [label,value] of [["Opened",h.purchase_date_known===false?"Unknown":h.acquisition_date],["Units",h.units],["Average cost",fmt(Number(h.cost)/Number(h.units))],["Previous close",fmt(h.previous_close)],["Latest price",fmt(h.price)],["Quote timestamp",h.quote_time||h.price_date],["Quote source",h.price_basis],["Quote freshness",h.freshness||(h.fresh?"Current session":"Older session")],["Stop status",v.status.replaceAll("_"," ")],["Capital risk",fmt(v.risk)],["Day P&L",fmt(v.day)],["Unrealised P&L",fmt(v.pnl)],["Trailing stop",fmt(h.current_trailing_stop)],["Hard stop",fmt(h.hard_stop)],["Stop basis",h.risk_basis],["Stop calculated through",h.risk_date]]) {const line=document.createElement("div");line.className="detail-line";const name=document.createElement("span"),amount=document.createElement("strong");name.textContent=label;amount.textContent=value??"—";line.append(name,amount);content.append(line);}
    if(h.risk_note){const note=document.createElement("p");note.className="muted";note.textContent=h.risk_note;content.append(note);}
    const close=document.createElement("button");close.className="secondary";close.textContent="Close";close.onclick=()=>modal.close();content.append(close);modal.showModal();
  }
  function filterHoldings(){const q=$("holding-search").value.trim().toLowerCase();const rows=[...$("holdings").querySelectorAll("tr[data-instrument]")];rows.forEach(row=>row.hidden=!row.cells[0].textContent.toLowerCase().includes(q));$("holding-count").textContent=`${rows.filter(row=>!row.hidden).length} of ${rows.length} positions · scroll right for stops and quote details`;}
  function updateHoldingTotals(){const hs=viewData?.holdings||[],vals=hs.map(holdingValues);const sum=key=>vals.length&&vals.every(v=>v[key]!=null)?vals.reduce((n,v)=>n+v[key],0):null;$("holding-totals").replaceChildren(...[["Invested",hs.reduce((n,h)=>n+Number(h.cost),0)],["Market value",sum("value")],["Unrealised P&L",sum("pnl")],["Day P&L",sum("day")],["Capital risk",sum("risk")]].map(([label,value])=>{const node=document.createElement("span");node.textContent=`${label}: ${fmt(value)}`;return node;}));}
  function applyLive(data){if(data.account_id!==$("account").value||!viewData)return;
    const capital=Number(viewData.net_contributed_capital);
    Screener.text($("absolute-return"),data.equity!=null&&capital>0?`${((Number(data.equity)-capital)/capital*100).toFixed(2)}%`:"Unavailable");
    const quotes=new Map(data.holdings.map(h=>[h.instrument_id,h]));
    viewData.holdings.forEach(h=>{const q=quotes.get(h.instrument_id);if(!q)return;for(const field of ["price","price_date","quote_time","price_basis","freshness","fresh","previous_close"])h[field]=q[field];h.day_pnl=q.day_pnl==null?null:String(Number(q.day_pnl)*Number(h.units)/Number(q.units));h.market_value=h.price==null?null:String(Number(h.price)*Number(h.units));});
    $("holdings").querySelectorAll("tr[data-instrument]").forEach(row=>{const h=viewData.holdings[Number(row.dataset.holdingIndex)];if(h)updateHoldingRow(row,h);});
    updateHoldingTotals();const risks=viewData.holdings.map(h=>holdingValues(h).risk);Screener.text($("risk"),risks.every(r=>r!=null)?fmt(risks.reduce((sum,r)=>sum+Math.max(0,r),0)):null);Screener.text($("equity"),fmt(data.equity));Screener.text($("unrealised"),fmt(data.unrealised_pnl));Screener.text($("day-pnl"),fmt(data.day_pnl));for(const [id,value] of [["unrealised",data.unrealised_pnl],["day-pnl",data.day_pnl]]){$(id).classList.toggle("positive",value!=null&&Number(value)>=0);$(id).classList.toggle("negative",value!=null&&Number(value)<0);}
    const connected=data.stream?.matches_account&&data.stream?.status==="CONNECTED";
    $("live-status").textContent=connected?`Connected · ${data.fresh_count}/${data.holding_count} fresh quotes`:data.stream?.matches_account?`${data.stream.status.toLowerCase()} · waiting for fresh quotes`:"Feed unavailable for this account";
    $("last-live-quote").textContent=data.observed_at?`Latest quote ${new Date(data.observed_at).toLocaleTimeString("en-IN",{timeZone:"Asia/Kolkata",hour12:false})} IST`:"Waiting for a timestamped quote";
    if(data.all_quotes_fresh&&data.day_pnl!=null&&data.observed_at&&data.observed_at!==lastChartTime){lastChartTime=data.observed_at;intradayRows.push({as_of_date:data.observed_at,equity:Number(data.day_pnl)});if(intradayRows.length>900)intradayRows.shift();drawChart("intraday-chart",intradayRows,"equity","var(--accent)");$("intraday-note").textContent=`${intradayRows.length} fresh observations since live monitoring started. Earlier session ticks are not reconstructed.`;}
    const breached=viewData.holdings.filter(h=>holdingValues(h).status.startsWith("below_")).length;$("portfolio-alert").hidden=!breached;$("portfolio-alert-text").textContent=`${breached} position(s) need a stop review.`;
  }
  async function stopLive(stopBroker=true){++liveGeneration;stream?.close();stream=null;const account=streamAccount;streamAccount=null;$("live-toggle").textContent="Go live";$("live-status").textContent="Live feed off";if(stopBroker&&account){try{const state=await Screener.api("/api/market/intraday/stream");if(state.enabled&&state.account_id===account)await Screener.api("/api/market/intraday/live-stream",{method:"POST",body:JSON.stringify({action:"stop"})});}catch(error){$("home-error").textContent=error.message;}}}
  async function toggleLive(){if(stream){await stopLive();return;}const account=$("account").value;if(!account||!viewData?.holdings.length)return;if(viewData.account_id!==account){$("home-error").textContent="Wait for this account’s valuation to finish loading.";return;}
    if($("as-of").value!==today()){$("home-error").textContent="Choose today's valuation date before starting the live feed.";return;}
    const token=++liveGeneration;$("live-toggle").disabled=true;$("live-status").textContent="Connecting to Kite…";
    try{const state=await Screener.api("/api/market/intraday/stream");if(token!==liveGeneration)return;if(state.enabled&&state.account_id!==account)throw Error("A live feed is active for another account. Stop that feed before switching.");
      if(state.enabled&&state.status==="ERROR")await Screener.api("/api/market/intraday/live-stream",{method:"POST",body:JSON.stringify({action:"stop"})});
      if(!state.enabled||state.status==="ERROR")await Screener.api("/api/market/intraday/live-stream",{method:"POST",body:JSON.stringify({action:"start",account_id:account,instrument_ids:[...new Set(viewData.holdings.map(h=>h.instrument_id))]})});
      if(token!==liveGeneration||account!==$("account").value){const latest=await Screener.api("/api/market/intraday/stream");if(latest.account_id===account&&latest.enabled)await Screener.api("/api/market/intraday/live-stream",{method:"POST",body:JSON.stringify({action:"stop"})});return;}streamAccount=account;
      stream=new EventSource(`/api/portfolio/accounts/${encodeURIComponent(account)}/ticker/stream?live=1&continuous=1`);
      stream.addEventListener("portfolio-ticker",event=>{if(token===liveGeneration){try{applyLive(JSON.parse(event.data));}catch(error){$("home-error").textContent=error.message;}}});
      stream.onerror=()=>{if(token===liveGeneration)$("live-status").textContent="Reconnecting · last values retained";};$("live-toggle").textContent="Stop live";$("home-error").textContent="";
    }catch(error){$("home-error").textContent=error.message;$("live-status").textContent="Could not connect";}finally{$("live-toggle").disabled=false;}
  }

  async function refreshCredentials() {
    const account=$("account").value;if(!account)return;
    if(!savedBrokerAccountId){connectKite();return;}
    const loginTab=window.open("about:blank","kite-account-login");
    try { const login=await Screener.api(`/api/broker-accounts/${encodeURIComponent(savedBrokerAccountId)}/authorize`,{method:"POST"});
      if(loginTab){loginTab.opener=null;loginTab.location=login.authorization_url;}
      else {$("home-error").textContent="Allow popups and click Refresh account credentials again.";}
    } catch(error){loginTab?.close();$("home-error").textContent=error.message;}
  }
  document.addEventListener("DOMContentLoaded", async () => {
    $("as-of").value = today(); $("refresh-home").onclick = refreshBroker;
    $("import-kite").onclick = previewImport;
    $("upload-tradebook").onclick = uploadTradebook;
    $("account").onchange = async () => { await stopLive(); intradayRows=[]; lastChartTime=null; drawChart("intraday-chart",[],"equity","var(--accent)"); brokerStatus().catch(error => { $("home-error").textContent = error.message; }); refresh(); };
    $("connect-kite").onclick = connectKite; $("refresh-credentials").onclick=refreshCredentials;
    $("edit-account").onclick = editAccount;
    $("holding-search").oninput=filterHoldings; drawChart("intraday-chart",[],"equity","var(--accent)"); $("live-toggle").onclick = toggleLive; $("add-account").onclick = () => openForm("account");
    $("manual-buy").onclick = () => openForm("buy"); $("manual-sell").onclick = () => openForm("sell"); $("capital-event").onclick = () => openForm("cash");
    $("as-of").onchange = async () => { await stopLive(); refresh(); };
    try { await accounts(); await refresh(); } catch (error) { $("home-error").textContent = error.message; }
  });
  window.addEventListener("pagehide", () => stream?.close());
})();
