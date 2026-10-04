(() => {
  const $ = id => document.getElementById(id);
  let strategies = [], rows = [], signalJobTimer;
  const isDaily = () => $("strategy").value === "positional_trend_following";
  function message(text, error = false) { $("rankings-error").textContent = error ? text : ""; $("ranking-status").textContent = error ? "" : text; }
  function chosenDate() { return $("signal-date").value; }
  function renderRows() {
    const query = $("ranking-search").value.trim().toLocaleLowerCase();
    const visible = rows.filter(row => JSON.stringify(row).toLocaleLowerCase().includes(query));
    const columns = [...new Set(visible.flatMap(row => Object.keys(row)))];
    const head = document.createElement("tr");
    columns.forEach(column => { const th = document.createElement("th"); th.textContent = column.replaceAll("_", " "); head.append(th); });
    $("ranking-head").replaceChildren(head);
    $("ranking-body").replaceChildren(...visible.map(row => {
      const tr = document.createElement("tr");
      columns.forEach(column => {
        const td = document.createElement("td"), value = row[column];
        if (column === "filtered" && isDaily()) {
          const badge = document.createElement("span"); badge.className = `status-chip ${value ? "status-approved" : ""}`; badge.textContent = value ? "BUY candidate" : "No entry"; td.append(badge);
        } else if (value && typeof value === "object") td.textContent = JSON.stringify(value);
        else td.textContent = value == null ? "—" : String(value);
        tr.append(td);
      });
      return tr;
    }));
    if (!visible.length) {
      const tr = document.createElement("tr"), td = document.createElement("td"); td.colSpan = Math.max(1, columns.length); td.className = "workflow-empty";
      td.textContent = rows.length ? "No rows match this filter." : "No ranking rows were returned for this date."; tr.append(td); $("ranking-body").replaceChildren(tr);
    }
    $("ranking-search-wrap").hidden = !rows.length;
  }
  function setSummary(items) {
    $("ranking-summary").replaceChildren(...items.map(([label, value]) => {
      const stat = document.createElement("div"); stat.className = "workflow-stat";
      const strong = document.createElement("strong"); strong.textContent = String(value);
      const caption = document.createElement("span"); caption.textContent = label; stat.append(strong, caption); return stat;
    }));
  }
  function syncStrategyFields() {
    const daily = isDaily();
    $("week-field").hidden = daily; $("session-field").hidden = !daily; $("build-signals").hidden = !daily;
    $("start-signal-worker").hidden = !daily; $("work-signal-once").hidden = !daily;
    $("ranking-help").textContent = daily
      ? "Positional Trend is a daily event strategy. Select a completed market session; build signals if none are saved for that date."
      : "Choose a strategy and week ending to view its published factor ranking.";
    $("ranking-title").textContent = daily ? "Daily trend signals" : "Weekly stock ranking";
    $("ranking-caption").textContent = daily
      ? "BUY candidates are highlighted. Other screened rows show why a stock did not qualify."
      : "Rows and columns are read from the selected strategy’s published ranking.";
    $("ranking-head").replaceChildren(); $("ranking-body").innerHTML = '<tr><td class="workflow-empty">Choose a date to load results.</td></tr>';
    $("ranking-summary").replaceChildren(); rows = [];
    if (daily) message("Select a completed session date to continue.");
  }
  async function weeks() {
    if (isDaily()) return;
    const result = await Screener.api(`/api/research/ranking-weeks?strategy_id=${encodeURIComponent($("strategy").value)}`);
    $("week").replaceChildren(...result.week_ends.map(day => new Option(day, day)));
    if (!result.week_ends.length) message("No weekly rankings have been published for this strategy yet.");
  }
  async function load() {
    message(""); $("ranking-body").innerHTML = '<tr><td class="workflow-empty">Loading ranking…</td></tr>';
    try {
      if (isDaily()) {
        if (!chosenDate()) throw new Error("Choose a completed session date first.");
        const response = await Screener.api(`/api/positional-trend/signals?as_of_date=${encodeURIComponent(chosenDate())}`);
        rows = response.signals.signals || [];
        const buys = rows.filter(row => row.filtered).length, exits = rows.filter(row => row.exit_signal).length;
        setSummary([["Session", response.signals.as_of_date], ["BUY candidates", buys], ["Exit signals", exits], ["Stocks screened", rows.length]]);
        message(`Loaded Positional Trend signals for ${response.signals.as_of_date}.`);
      } else {
        if (!$("week").value) throw new Error("No weekly ranking is available. Choose another strategy or run research first.");
        const response = await Screener.api(`/api/research/rankings?week_end=${encodeURIComponent($("week").value)}&strategy_id=${encodeURIComponent($("strategy").value)}&limit=500`);
        rows = response.members || [];
        setSummary([["Week ending", response.week_end], ["Strategy", strategies.find(item => item.strategy_id === response.strategy_id)?.definition.strategy.name || response.strategy_id], ["Stocks ranked", rows.length]]);
        message(`Loaded ${rows.length} ranked stocks for the week ending ${response.week_end}.`);
      }
      renderRows();
    } catch (error) {
      rows = []; renderRows(); message(error.message || "Unable to load ranking.", true);
      if (isDaily() && /not found/i.test(error.message)) message("No current signal artifact exists for this date. Build signals below to create it.");
    }
  }
  async function buildSignals() {
    if (!chosenDate()) { message("Choose a completed session date first.", true); return; }
    try {
      const job = await Screener.api("/api/positional-trend/signals/build", {method:"POST",body:JSON.stringify({as_of_date:chosenDate(),universe:"SNAPSHOT_NIFTY500"})});
      message(`Signal build queued as job ${job.job_id} (${job.status}). The worker must process it before results are available.`);
      clearInterval(signalJobTimer); signalJobTimer = setInterval(async () => {
        try {
          const status = await Screener.api(`/api/operations/jobs/${job.job_id}`);
          if (["SUCCEEDED", "FAILED", "CANCELLED"].includes(status.status)) {
            clearInterval(signalJobTimer);
            if (status.status === "SUCCEEDED") { message(`Signal build completed for ${chosenDate()}.`); await load(); }
            else message(`Signal build ${status.status.toLowerCase()}: ${status.last_error || "review the job log"}`, true);
          }
        } catch (error) { clearInterval(signalJobTimer); message(error.message, true); }
      }, 2500);
    } catch (error) { message(error.message || "Unable to queue signal build.", true); }
  }
  document.addEventListener("DOMContentLoaded", async () => {
    try {
      const data = await Screener.api("/api/strategies/active"); strategies = data.strategies || [];
      $("strategy").replaceChildren(...strategies.map(strategy => new Option(strategy.definition.strategy.name, strategy.strategy_id)));
      $("signal-date").value = "";
      if (!strategies.length) { message("No active strategies are available.", true); return; }
      $("strategy").onchange = async () => { syncStrategyFields(); try { await weeks(); } catch (error) { message(error.message, true); } };
      $("load-rankings").onclick = load; $("week").onchange = load; $("signal-date").onchange = () => message("Date selected. Load saved signals or build them if they are not available.");
      $("build-signals").onclick = buildSignals; $("ranking-search").oninput = renderRows;
      $("start-signal-worker").onclick = async () => { try { const result = await Screener.api("/api/operations/worker/start", {method:"POST"}); message(result.running ? "Research worker is running. It will process queued signal jobs." : "Research worker started."); } catch (error) { message(error.message, true); } };
      $("work-signal-once").onclick = async () => { try { const result = await Screener.api("/api/operations/worker/work-once", {method:"POST"}); message(result.executed ? `Processed job ${result.job.job_id} (${result.job.status}).` : "No queued job was available."); } catch (error) { message(error.message, true); } };
      syncStrategyFields(); await weeks();
      if (!isDaily() && $("week").value) await load();
    } catch (error) { message(error.message || "Unable to load active strategies.", true); }
  });
  window.addEventListener("pagehide", () => clearInterval(signalJobTimer));
})();
