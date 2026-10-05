(() => {
  const $ = id => document.getElementById(id);
  const terminal = new Set(["SUCCEEDED", "FAILED", "CANCELLED"]);
  let activeJob = false;
  let strategyRows = [];

  function showError(message = "") { $("backtest-error").textContent = message; }
  function localDate(date) { return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`; }
  const pct = (value, alreadyPercent = false) => `${(Number(value) * (alreadyPercent ? 1 : 100)).toFixed(2)}%`;

  async function strategies() {
    const data = await Screener.api("/api/strategies/active");
    strategyRows = data.strategies || [];
    $("strategy").replaceChildren(...strategyRows.map(item => new Option(item.definition?.strategy?.name || item.strategy_id, item.strategy_id)));
    updatePolicyControls();
  }

  function updatePolicyControls() {
    const selected = strategyRows.find(item => item.strategy_id === $("strategy").value);
    const definition = selected?.definition || {};
    const policy = definition.portfolio_policy || {};
    $("starting-cash").value = policy.initial_capital || 200000;
    $("max-positions").value = policy.max_positions || 15;
    const positional = $("strategy").value === "positional_trend_following";
    $("common-options").hidden = positional;
    $("positional-options").hidden = !positional;
  }

  async function loadRuns() {
    showError();
    try {
      const limit = Math.max(1, Math.min(100, Number($("run-limit").value) || 50));
      const data = await Screener.api(`/api/backtests/runs?limit=${limit}`);
      $("runs").replaceChildren(...data.runs.map(run => {
        const button = document.createElement("button");
        button.className = "secondary";
        button.textContent = "Open report";
        button.onclick = () => showRun(run.run_id);
        return Screener.row([run.run_id, run.strategy_id || "—", run.end_date || run.as_of_date || run.created_at || "—", button]);
      }));
      if (!data.runs.length) $("runs").append(Screener.row(["No saved runs yet", "", "", ""]));
    } catch (error) { showError(error.message); }
  }

  function showMetrics(run) {
    const metrics = run.metrics || run.performance || run.summary || {};
    const preferred = [
      ["Total return", metrics.total_return ?? metrics.total_return_pct ?? metrics.net_return_pct, value => pct(value, metrics.total_return == null)],
      ["Max drawdown", metrics.max_drawdown ?? metrics.max_drawdown_pct, value => pct(value, metrics.max_drawdown == null)],
      ["Closed trades", metrics.closed_trades ?? metrics.trade_count ?? run.trade_counts?.sell, value => String(value)],
      ["Sharpe ratio", metrics.sharpe ?? metrics.sharpe_ratio, value => Number(value).toFixed(2)],
      ["CAGR", metrics.cagr, value => pct(value)],
      ["Win rate", metrics.win_rate ?? metrics.win_rate_pct, value => pct(value, metrics.win_rate == null)],
    ];
    $("run-summary").replaceChildren(...preferred.map(([label, value, format]) => {
      const card = document.createElement("div"); card.className = "card";
      const name = document.createElement("div"); name.className = "metric-label"; name.textContent = label;
      const amount = document.createElement("div"); amount.className = "metric"; amount.textContent = value == null ? "—" : format(value);
      card.append(name, amount); return card;
    }));
  }

  function renderReportTables(run) {
    const host = $("run-tables"); host.replaceChildren();
    const makeTable = (title, rows, preferred) => {
      if (!Array.isArray(rows) || !rows.length) return;
      const section = document.createElement("section"); section.style.marginTop = "1rem";
      const heading = document.createElement("h3"); heading.textContent = title;
      const wrap = document.createElement("div"); wrap.className = "table-wrap";
      const table = document.createElement("table");
      const keys = preferred.filter(key => rows.some(row => Object.hasOwn(row, key)));
      const cols = keys.length ? keys : Object.keys(rows[0]).slice(0, 8);
      const head = document.createElement("thead"); head.append(Screener.row(cols.map(key => key.replaceAll("_", " "))));
      const body = document.createElement("tbody");
      rows.slice(0, 100).forEach(row => body.append(Screener.row(cols.map(key => {
        const value = row[key]; return value && typeof value === "object" ? JSON.stringify(value) : value;
      }))));
      table.append(head, body); wrap.append(table); section.append(heading, wrap); host.append(section);
    };
    makeTable("Equity curve", run.equity_curve || run.curve, ["date", "value", "equity"]);
    makeTable("Trade and fill log", run.trade_log || run.fills || run.trades, ["as_of_date", "side", "symbol", "instrument_id", "units", "price", "decision_type", "fee"]);
    makeTable("Open positions at period end", run.open_positions || run.open_holdings, ["symbol", "instrument_id", "units", "average_cost", "last_price", "market_value"]);
    makeTable("Annual returns", run.annual_returns, ["year", "return", "start_value", "end_value"]);
  }

  async function showRun(runId) {
    showError();
    try {
      const data = await Screener.api(`/api/backtests/runs/${encodeURIComponent(runId)}`);
      showMetrics(data.run || {}); renderReportTables(data.run || {});
      $("run-detail").textContent = JSON.stringify(data, null, 2);
    } catch (error) { showError(error.message); }
  }

  function command() {
    const strategy = $("strategy").value;
    const payload = {
      strategy_id: strategy,
      start_date: $("start-date").value,
      end_date: $("end-date").value,
      starting_cash: Number($("starting-cash").value),
      max_positions: Number($("max-positions").value),
    };
    if (strategy === "positional_trend_following") {
      payload.risk_pct = Number($("risk-pct").value || 1);
      payload.max_order_pct = Number($("max-order-pct").value || 20);
      payload.adv_participation_pct = Number($("adv-participation").value || 5);
      payload.round_trip_cost_bps = Number($("round-trip-cost").value || 20);
      payload.universe = "SNAPSHOT_NIFTY500";
      return payload;
    }
    Object.assign(payload, {
      check_daily_sl: $("check-daily-sl").checked,
      mid_week_buy: $("mid-week-buy").checked,
      enable_pyramiding: $("enable-pyramiding").checked,
      pyramid_fraction: Number($("pyramid-fraction").value),
      slippage_bps: Number($("slippage").value),
      fee_bps: Number($("fee").value),
      tax_bps: Number($("tax").value),
      rebalance_frequency: $("rebalance").value,
    });
    return payload;
  }

  async function run() {
    showError();
    const payload = command();
    if (!payload.start_date || !payload.end_date || payload.start_date > payload.end_date) {
      showError("Choose a valid completed start and end date."); return;
    }
    activeJob = true; $("run-backtest").disabled = true;
    $("job-status").textContent = "Submitting simulation…";
    try {
      const fingerprint = `ui-backtest:${Screener.id()}`;
      const job = await Screener.api("/api/operations/jobs", { method: "POST", body: JSON.stringify({ fingerprint, kind: "backtest.run", payload }) });
      await watchJob(job.job_id);
    } catch (error) { showError(error.message); $("job-status").textContent = "Could not start simulation"; }
    finally { activeJob = false; $("run-backtest").disabled = false; }
  }

  async function watchJob(jobId) {
    while (activeJob) {
      const job = await Screener.api(`/api/operations/jobs/${jobId}`);
      const progress = job.current_progress?.message || job.current_progress?.stage || "Working";
      $("job-status").textContent = `${job.status}: ${progress}`;
      if (terminal.has(job.status)) {
        if (job.status === "SUCCEEDED" && job.result?.run_id) {
          $("job-status").textContent = `Completed · ${job.result.fill_count ?? 0} fills across ${job.result.session_count ?? "—"} sessions`;
          await Promise.all([loadRuns(), showRun(job.result.run_id)]);
        } else if (job.status !== "SUCCEEDED") {
          showError(job.last_error || `Simulation ${job.status.toLowerCase()}.`);
        }
        return;
      }
      await new Promise(resolve => setTimeout(resolve, 1400));
    }
  }

  document.addEventListener("DOMContentLoaded", async () => {
    const today = new Date(); today.setDate(today.getDate() - 1);
    const end = localDate(today);
    const start = new Date(today); start.setFullYear(start.getFullYear() - 3);
    $("end-date").value = end; $("start-date").value = localDate(start);
    $("run-backtest").onclick = run; $("load-runs").onclick = loadRuns;
    $("strategy").onchange = updatePolicyControls;
    try { await strategies(); await loadRuns(); } catch (error) { showError(error.message); }
  });
})();
