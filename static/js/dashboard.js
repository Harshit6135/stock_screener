// --- Navigation ---
        function switchTab(tabId) {
            document.querySelectorAll('.tab-pane').forEach(el => el.classList.remove('active'));
            document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));

            document.getElementById('tab-' + tabId).classList.add('active');
            // Find button that calls this function with this tabId
            // Simple approach: select by index or just iterate. 
            // Better: add specific IDs to buttons. But iterating is fine.
            const btns = document.querySelectorAll('.tab-btn');
            if (tabId === 'pipeline') btns[0].classList.add('active');
            if (tabId === 'portfolio') { btns[1].classList.add('active'); loadPortfolio(); }
            if (tabId === 'actions') { btns[2].classList.add('active'); initActionsDate(); }
            if (tabId === 'backtest') { btns[3].classList.add('active'); initBacktestDates(); loadBacktestHistory(); }
            if (tabId === 'config') { btns[4].classList.add('active'); loadConfig(); }
        }

        function showLoading(msg) {
            document.getElementById('loading-text').innerText = msg;
            document.getElementById('loading-overlay').classList.remove('hidden');
        }
        function hideLoading() {
            document.getElementById('loading-overlay').classList.add('hidden');
        }

        function log(msg) {
            const el = document.getElementById('pipeline-console');
            const time = new Date().toLocaleTimeString();
            el.innerHTML += `<div><span style="color:#555">[${time}]</span> ${msg}</div>`;
            el.scrollTop = el.scrollHeight;
        }

        // --- MANUAL TRADES ---
        function openManualBuy() {
            document.getElementById('mb-date').value = new Date().toISOString().split('T')[0];
            document.getElementById('mb-symbol').value = '';
            document.getElementById('mb-units').value = '';
            document.getElementById('mb-price').value = '';
            document.getElementById('mb-capital').value = '';
            document.getElementById('manual-buy-modal').classList.remove('hidden');
        }

        function openManualSell() {
            document.getElementById('ms-date').value = new Date().toISOString().split('T')[0];
            document.getElementById('ms-symbol').value = '';
            document.getElementById('ms-units').value = '';
            document.getElementById('ms-price').value = '';
            document.getElementById('manual-sell-modal').classList.remove('hidden');
        }

        async function submitManualBuy() {
            const symbol = document.getElementById('mb-symbol').value.toUpperCase();
            const date = document.getElementById('mb-date').value;
            const units = parseInt(document.getElementById('mb-units').value);
            const price = parseFloat(document.getElementById('mb-price').value);
            const reason = document.getElementById('mb-reason').value;

            if (!symbol || !units || !price) return alert('Fill all fields');

            const payload = [{
                symbol: symbol,
                date: date,
                units: units,
                price: price,
                reason: reason,
                config_name: "momentum_config"
            }];

            showLoading('Processing Buy...');
            try {
                const res = await fetch('/api/v1/investment/manual/buy', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const data = await res.json();
                if (res.ok) {
                    alert('Success: ' + data.message);
                    document.getElementById('manual-buy-modal').classList.add('hidden');
                    loadPortfolio();
                } else {
                    alert('Error: ' + data.message);
                }
            } catch (e) { alert(e.message); }
            hideLoading();
        }

        async function submitManualSell() {
            const symbol = document.getElementById('ms-symbol').value.toUpperCase();
            const date = document.getElementById('ms-date').value;
            const units = parseInt(document.getElementById('ms-units').value);
            const price = parseFloat(document.getElementById('ms-price').value);
            const reason = document.getElementById('ms-reason').value;

            if (!symbol || !units || !price) return alert('Fill all fields');

            const payload = {
                symbol: symbol,
                date: date,
                units: units,
                price: price,
                reason: reason
            };

            showLoading('Processing Sell...');
            try {
                const res = await fetch('/api/v1/investment/manual/sell', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const data = await res.json();
                if (res.ok) {
                    alert('Success: ' + data.message);
                    document.getElementById('manual-sell-modal').classList.add('hidden');
                    loadPortfolio();
                } else {
                    alert('Error: ' + data.message);
                }
            } catch (e) { alert(e.message); }
            hideLoading();
        }

        // --- CAPITAL EVENTS ---
        function openCapitalEventModal() {
            document.getElementById('ce-date').value = new Date().toISOString().split('T')[0];
            document.getElementById('ce-amount').value = '';
            document.getElementById('ce-note').value = '';
            document.getElementById('capital-event-modal').classList.remove('hidden');
        }

        async function submitCapitalEvent() {
            const date = document.getElementById('ce-date').value;
            const type = document.getElementById('ce-type').value;
            const amount = parseFloat(document.getElementById('ce-amount').value);
            const note = document.getElementById('ce-note').value;

            if (!amount || amount <= 0) return alert('Enter valid amount');

            showLoading('Processing Capital Event...');
            try {
                const res = await fetch('/api/v1/investment/capital-events', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        date: date,
                        event_type: type,
                        amount: amount,
                        note: note
                    })
                });
                const data = await res.json();
                if (res.ok) {
                    alert('Success: ' + data.message);
                    document.getElementById('capital-event-modal').classList.add('hidden');
                    loadPortfolio();
                } else {
                    alert('Error: ' + data.message);
                }
            } catch (e) { alert(e.message); }
            hideLoading();
        }


        // --- CALCULATOR ---
        function calcUnits() {
            const capital = parseFloat(document.getElementById('mb-capital').value) || 0;
            const price = parseFloat(document.getElementById('mb-price').value) || 0;
            if (capital > 0 && price > 0) {
                document.getElementById('mb-units').value = Math.floor(capital / price);
            }
        }

        function calcCapital() {
            const units = parseInt(document.getElementById('mb-units').value) || 0;
            const price = parseFloat(document.getElementById('mb-price').value) || 0;
            if (units > 0 && price > 0) {
                document.getElementById('mb-capital').value = (units * price).toFixed(2);
            }
        }

        // --- DataTables Helper ---
        function destroyDataTable(tableId) {
            if ($.fn.DataTable.isDataTable(tableId)) {
                $(tableId).DataTable().destroy();
            }
        }
        function makeTableSortable(tableId, options = {}) {
            $(tableId).DataTable(Object.assign({
                paging: false,
                searching: false,
                info: false,
                order: [],
                autoWidth: false
            }, options));
        }

        // --- Init Helpers ---
        document.addEventListener('DOMContentLoaded', () => {
            // Set today's date for inputs
            const today = new Date().toISOString().split('T')[0];
            document.getElementById('cleanup-date').value = today;
            document.getElementById('cleanup-date').value = today;

            // Auto-load portfolio on start
            switchTab('portfolio');
        });

        // --- PIPELINE ---
        async function runPipeline() {
            const payload = {
                init: document.getElementById('step-init').checked,
                marketdata: document.getElementById('step-market').checked,
                historical: document.getElementById('step-historical').checked,
                indicators: document.getElementById('step-ind').checked,
                percentile: document.getElementById('step-pct').checked,
                score: document.getElementById('step-score').checked,
                ranking: document.getElementById('step-rank').checked,
                yfinance_batch_size: parseInt(document.getElementById('yf-batch').value) || 100,
                yfinance_sleep_time: parseInt(document.getElementById('yf-sleep').value) || 4,
                yfinance_rate_limit_wait: parseInt(document.getElementById('yf-429-wait').value) || 120
            };

            const consoleEl = document.getElementById('pipeline-console');
            consoleEl.innerHTML = '';  // clear old output

            // Open SSE log stream BEFORE hitting the pipeline endpoint so every
            // backend log line appears in the console in real-time.
            const es = new EventSource('/api/v1/app/logs/stream');
            es.onmessage = (e) => {
                if (e.data === '[PING]') return;
                const line = document.createElement('div');
                const text = e.data;
                if (text.startsWith('ERROR')) line.style.color = '#ff6b6b';
                else if (text.startsWith('WARNING')) line.style.color = '#ffd93d';
                else line.style.color = '#a8ff78';
                line.textContent = text;
                consoleEl.appendChild(line);
                consoleEl.scrollTop = consoleEl.scrollHeight;
                // Update the loading overlay with the last log line (strip level/name prefix)
                const loadingText = document.querySelector('.loading-text');
                if (loadingText) loadingText.textContent = text.replace(/^[A-Z]+ \| [^\|]+ \| /, '');
            };
            es.onerror = () => es.close();

            const runBtn = document.getElementById('run-pipeline-btn');
            if (runBtn) {
                runBtn.disabled = true;
                runBtn.innerHTML = 'Running... <span class="spinner" style="width:12px;height:12px;border-width:2px;display:inline-block;margin-left:5px;"></span>';
            }

            try {
                const res = await fetch('/api/v1/app/run-pipeline', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const data = await res.json();

                const stepLabels = {
                    kite_auth: '0. Kite Auth',
                    init: '1. Init App',
                    marketdata: '2. Market Data',
                    indicators: '3. Indicators',
                    percentile: '4. Percentiles',
                    score: '5. Scores',
                    ranking: '6. Rankings',
                };

                log('─'.repeat(50));
                if (res.ok) {
                    const aborted = data.message && data.message.includes('aborted');
                    log(aborted ? '⚠️  Pipeline aborted — see steps below:' : '✅ Pipeline Complete!');
                    Object.entries(data.results || {}).forEach(([step, status]) => {
                        const label = stepLabels[step] || step;
                        let icon = '✅';
                        if (typeof status === 'string' && status.startsWith('failed')) icon = '❌';
                        else if (typeof status === 'string' && status.startsWith('skipped')) icon = '⏭';
                        log(`   ${icon} ${label}: ${status}`);
                    });
                } else {
                    log(`❌ Error: ${data.message || 'Unknown error'}`);
                }
            } catch (e) {
                log(`❌ Network Error: ${e.message}`);
            } finally {
                es.close();
                const runBtn = document.getElementById('run-pipeline-btn');
                if (runBtn) {
                    runBtn.disabled = false;
                    runBtn.innerHTML = 'Run Selected Steps';
                }
            }
        }


        async function syncInstruments() {
            const btn = document.getElementById('sync-instr-btn');
            btn.disabled = true;
            showLoading('Syncing instruments... fetching Kite data');
            log('--> Starting instrument sync (BE/EQ series detection)...');
            try {
                const res = await fetch('/api/v1/init/sync', { method: 'POST' });
                const data = await res.json();
                if (res.ok) {
                    log(`✅ Instrument Sync Complete!`);
                    log(`   • Checked: ${data.checked} symbols`);
                    log(`   • Changed: ${data.changed} symbols`);
                    log(`   • Errors : ${data.errors} symbols`);
                } else {
                    log(`❌ Sync Error: ${data.message || JSON.stringify(data)}`);
                }
            } catch (e) {
                log(`❌ Network Error: ${e.message}`);
            }
            hideLoading();
            btn.disabled = false;
        }

        async function runCleanup() {
            const date = document.getElementById('cleanup-date').value;
            if (!date) return alert('Select a date');
            if (!confirm(`Are you sure you want to delete data after ${date}? This cannot be undone.`)) return;

            showLoading('Cleaning up data...');
            try {
                const res = await fetch(`/api/v1/app/cleanup?start_date=${date}`, { method: 'DELETE' });
                const data = await res.json();
                log(`🗑 Cleanup result: ${data.message}`);
            } catch (e) {
                log(`❌ Cleanup failed: ${e.message}`);
            }
            hideLoading();
        }

        // --- PORTFOLIO ---
        let portfolioChartInstance = null;

        async function loadPortfolio() {
            showLoading('Loading Portfolio...');

            try {
                // 1. Load Config (for max positions)
                // We assume momentum_config for now, or we could make this dynamic
                const cRes = await fetch('/api/v1/config/momentum_config');
                const config = await cRes.json();
                const maxPositions = config.max_positions || 15;
                document.getElementById('max-pos').innerText = maxPositions;
                window._portHardSlPct = config.hard_sl_percent || 0.03;  // used by renderHoldings

                // 2. Load Holdings (Latest)
                const hRes = await fetch('/api/v1/investment/holdings');
                const holdings = await hRes.json();
                renderHoldings(holdings);
                renderPortfolioChart(holdings);

                // 3. Load Summary (Latest)
                const sRes = await fetch('/api/v1/investment/summary');
                const summary = await sRes.json();

                if (summary && summary.portfolio_value) {
                    const fmt = (v) => parseFloat(v).toLocaleString(undefined, { maximumFractionDigits: 0 });
                    document.getElementById('sum-val').innerText = '₹' + fmt(summary.portfolio_value);
                    document.getElementById('sum-inv').innerText = '₹' + fmt(summary.invested_value || 0);

                    const unrealized = parseFloat(summary.unrealized_gain || 0);
                    const realized = parseFloat(summary.realized_gain || 0);

                    const elUnrealized = document.getElementById('sum-unrealized');
                    elUnrealized.innerText = '₹' + fmt(unrealized);
                    elUnrealized.className = 'metric-value ' + (unrealized >= 0 ? 'pos-val' : 'neg-val');

                    const elRealized = document.getElementById('sum-realized');
                    elRealized.innerText = '₹' + fmt(realized);
                    elRealized.className = 'metric-value ' + (realized >= 0 ? 'pos-val' : 'neg-val');

                    const elPortfolioRisk = document.getElementById('sum-portfolio-risk');
                    elPortfolioRisk.innerText = '₹' + fmt(summary.portfolio_risk || 0);
                    elPortfolioRisk.className = 'metric-value ' + (summary.portfolio_risk <= 0 ? 'pos-val' : 'neg-val');

                    const elCapitalRisk = document.getElementById('sum-capital-risk');
                    elCapitalRisk.innerText = '₹' + fmt(summary.capital_risk || 0);
                    elCapitalRisk.className = 'metric-value ' + (summary.capital_risk <= 0 ? 'pos-val' : 'neg-val');

                    document.getElementById('sum-cash').innerText = '₹' + fmt(summary.remaining_capital || 0);
                    document.getElementById('pos-count').innerText = holdings.length;

                    // Absolute Return %
                    const absReturn = parseFloat(summary.gain_percentage || 0);
                    const elAbsReturn = document.getElementById('sum-abs-return');
                    elAbsReturn.innerText = absReturn.toFixed(2) + '%';
                    elAbsReturn.className = 'metric-value ' + (absReturn >= 0 ? 'pos-val' : 'neg-val');

                    // XIRR
                    const xirr = summary.xirr;
                    const elXirr = document.getElementById('sum-xirr');
                    if (xirr !== null && xirr !== undefined) {
                        elXirr.innerText = parseFloat(xirr).toFixed(2) + '%';
                        elXirr.className = 'metric-value ' + (xirr >= 0 ? 'pos-val' : 'neg-val');
                    } else {
                        elXirr.innerText = 'N/A';
                    }
                } else {
                    ['sum-val', 'sum-inv', 'sum-unrealized', 'sum-realized', 'sum-cash', 'sum-abs-return', 'sum-xirr'].forEach(id => {
                        document.getElementById(id).innerText = '-';
                    });
                }

                // 4. Load Rankings (Latest)
                const rRes = await fetch('/api/v1/ranking/top/20');
                const rankings = await rRes.json();
                renderRankings(rankings);

                // 5. Load Equity Curve & Drawdown
                loadEquityCurve();

                // 6. Load Trade Journal
                loadTradeJournal();

            } catch (e) {
                console.error(e);
            }
            hideLoading();
        }

        function renderPortfolioChart(holdings) {
            const canvas = document.getElementById('portfolioChart');
            if (!canvas) return;
            const ctx = canvas.getContext('2d');

            if (portfolioChartInstance) {
                portfolioChartInstance.destroy();
            }

            if (!holdings || holdings.length === 0) {
                return;
            }

            const labels = [];
            const data = [];
            const colors = [];

            holdings.forEach((h, i) => {
                const price = parseFloat(h.current_price || 0);
                const units = parseFloat(h.units || 0);
                const val = price * units;

                // Only include non-zero positions to avoid clutter and NaNs
                if (val > 0.01) {
                    labels.push(h.symbol);
                    data.push(val);
                    colors.push(`hsl(${i * 360 / holdings.length}, 70%, 60%)`);
                }
            });

            if (data.length === 0) return;

            portfolioChartInstance = new Chart(ctx, {
                type: 'doughnut',
                data: {
                    labels: labels,
                    datasets: [{
                        data: data,
                        backgroundColor: colors,
                        borderWidth: 1,
                        borderColor: '#181b21'
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { position: 'right', labels: { color: '#94a3b8' } }
                    }
                }
            });
        }



        function renderHoldings(holdings) {
            destroyDataTable('#holdings-table');
            const tbody = document.getElementById('holdings-body');
            const tfoot = document.getElementById('holdings-foot');
            tbody.innerHTML = '';
            tfoot.innerHTML = '';

            if (!holdings || !holdings.length) {
                tbody.innerHTML = '<tr><td colspan="10" class="text-center">No holdings found for this date</td></tr>';
                return;
            }

            let totalInv = 0, totalVal = 0, totalPnL = 0, totalCapRisk = 0;
            const hardSlPct = window._portHardSlPct || 0.03;

            holdings.forEach(h => {
                const entryPrice = parseFloat(h.entry_price || 0);
                const avgPrice = parseFloat(h.avg_price || h.entry_price || 0);
                const currentPrice = parseFloat(h.current_price || 0);
                const currentSl = parseFloat(h.current_sl || 0);
                const hardSlPrice = currentSl > 0 ? +(currentSl * (1 - hardSlPct)).toFixed(2) : 0;
                const units = parseFloat(h.units || 0);

                const inv = avgPrice * units;
                const val = currentPrice * units;
                const pnl = val - inv;
                const pnlPct = inv !== 0 ? (pnl / inv) * 100 : 0;
                const capRisk = units * (avgPrice - currentSl);

                totalInv += inv;
                totalVal += val;
                totalPnL += pnl;
                if (currentSl > 0) totalCapRisk += capRisk;

                const row = `<tr data-symbol="${h.symbol}">
                    <td><strong>${h.symbol}</strong></td>
                    <td class="text-center" data-sort="${h.entry_date}">${h.entry_date}</td>
                    <td class="text-center" data-sort="${units}">${units}</td>
                    <td class="text-center" data-sort="${avgPrice}">₹${avgPrice.toFixed(2)}</td>
                    <td class="text-center live-current" data-sort="${currentPrice}">₹${currentPrice.toFixed(2)}</td>
                    <td class="text-center" data-sort="${currentSl}" style="color:var(--warning);">₹${currentSl.toFixed(2)}</td>
                    <td class="text-center" data-sort="${hardSlPrice}" style="color:var(--danger); font-weight:600;">₹${hardSlPrice > 0 ? hardSlPrice.toFixed(2) : '-'}</td>
                    <td class="text-center ${capRisk > 0 ? 'neg-val' : 'pos-val'}" data-sort="${capRisk}">₹${currentSl > 0 ? capRisk.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '-'}</td>
                    <td class="text-center" data-sort="${inv}">₹${inv.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
                    <td class="text-center live-value" data-sort="${val}">₹${val.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
                    <td class="text-center live-pnl ${pnl >= 0 ? 'pos-val' : 'neg-val'}" data-sort="${pnl}">₹${pnl.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
                    <td class="text-center live-pnlpct ${pnl >= 0 ? 'pos-val' : 'neg-val'}" data-sort="${pnlPct}">${pnlPct.toFixed(2)}%</td>
                    <td class="text-center live-day-pnl" data-sort="0" style="color:var(--text-muted);">-</td>
                </tr>`;
                tbody.innerHTML += row;
            });

            // Totals
            const totalRow = `<tr style="font-weight:700; background:#232730;">
                    <td colspan="7" class="text-center">TOTALS</td>
                    <td class="text-center ${totalCapRisk > 0 ? 'neg-val' : 'pos-val'}">₹${totalCapRisk.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
                    <td class="text-center">₹${totalInv.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
                    <td class="text-center" id="live-total-val">₹${totalVal.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
                    <td class="text-center ${totalPnL >= 0 ? 'pos-val' : 'neg-val'}" id="live-total-pnl">₹${totalPnL.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
                    <td class="text-center ${totalPnL >= 0 ? 'pos-val' : 'neg-val'}">${totalInv !== 0 ? ((totalPnL / totalInv) * 100).toFixed(2) : '0.00'}%</td>
                    <td class="text-center" id="live-total-day-pnl" style="color:var(--text-muted);">-</td>
                </tr>`;
            tfoot.innerHTML = totalRow;
            makeTableSortable('#holdings-table', { searching: true });
        }

        function renderRankings(rankings) {
            destroyDataTable('#rankings-table');
            const body = document.querySelector('#rankings-table tbody');
            body.innerHTML = '';
            rankings.forEach(r => {
                const row = `<tr>
                    <td data-sort="${r.rank}">#${r.rank}</td>
                    <td>${r.tradingsymbol}</td>
                    <td class="text-right" data-sort="${r.composite_score}">${r.composite_score.toFixed(2)}</td>
                </tr>`;
                body.innerHTML += row;
            });
            makeTableSortable('#rankings-table', { paging: true, pageLength: 10, info: true });
        }

        // --- ACTIONS ---
        async function initActionsDate() {
            // Fetch available dates
            const res = await fetch('/api/v1/actions/dates');
            const dates = await res.json();
            if (dates.length > 0) {
                // select latest
                document.getElementById('actions-date').value = dates[0]; // assumes sorted desc
                loadActions();
            }
        }

        async function generateActions() {
            const pyramiding = document.getElementById('pyramid-toggle').checked;
            const dailySl = document.getElementById('daily-sl-toggle').checked;
            const midWeekBuy = document.getElementById('midweek-buy-toggle').checked;
            showLoading('Generating Actions...');
            try {
                let url = '/api/v1/actions/generate?config_name=momentum_config';
                if (pyramiding) url += '&enable_pyramiding=true';
                if (dailySl) url += '&check_daily_sl=true';
                if (midWeekBuy) url += '&mid_week_buy=true';
                const date = document.getElementById('actions-date').value;
                if (date) url += `&date=${date}`;
                const res = await fetch(url, { method: 'POST' });
                const data = await res.json();
                if (res.ok) {
                    alert('Actions Generated: ' + data.message);
                    loadActions();
                } else {
                    alert('Error: ' + data.message);
                }
            } catch (e) { alert(e.message); }
            hideLoading();
        }

        async function loadActions() {
            const date = document.getElementById('actions-date').value;
            if (!date) return;

            showLoading('Loading Actions...');
            const res = await fetch(`/api/v1/actions/?date=${date}`);
            const actions = await res.json();

            destroyDataTable('#actions-table');
            const tbody = document.getElementById('actions-body');
            tbody.innerHTML = '';

            if (!actions.length) {
                tbody.innerHTML = '<tr><td colspan="9" class="text-center">No actions found</td></tr>';
                hideLoading();
                return;
            }

            const summaryRes = await fetch('/api/v1/investment/summary');
            const summaryData = await summaryRes.json();
            const availableCash = summaryData ? parseFloat(summaryData.remaining_capital || 0) : 0;

            window._actionsData = actions; // Store for projection updates
            window._baseCash = availableCash;

            actions.forEach(a => {
                const badgeClass = a.type === 'buy' ? 'badge-buy' : a.type === 'sell' ? 'badge-sell' : 'badge-swap';

                let actionBtn = '';
                let unitsTd = `<td data-sort="${a.units}">${a.units}</td>`;
                let priceTd = `<td data-sort="${a.execution_price || a.prev_close || 0}">${a.execution_price || a.prev_close || '-'}</td>`;

                if (a.status === 'Pending') {
                    // Make inputs for units & price
                    const curUnits = a.units || 0;
                    const curPrice = a.execution_price || a.prev_close || 0;

                    unitsTd = `<td><input type="number" id="units-${a.action_id}" value="${curUnits}" class="table-input" style="width: 70px; padding: 2px 5px;" onchange="updateProjection('${a.action_id}')" min="0"></td>`;
                    priceTd = `<td><input type="number" step="0.05" id="price-${a.action_id}" value="${curPrice}" class="table-input" style="width: 90px; padding: 2px 5px;" onchange="updateProjection('${a.action_id}')" min="0"></td>`;

                    actionBtn = `
                        <button class="badge badge-buy" style="border:none;cursor:pointer;" onclick="confirmInlineApprove('${a.action_id}', '${a.symbol}')">Approve</button>
                        <button class="badge badge-sell" style="border:none;cursor:pointer;" onclick="updateAction('${a.action_id}', 'Rejected')">Reject</button>
                    `;
                }

                tbody.innerHTML += `<tr>
                    <td data-sort="${a.action_date}">${a.action_date}</td>
                    <td data-sort="${a.type}"><span class="badge ${badgeClass}">${a.type.toUpperCase()}</span></td>
                    <td><b>${a.symbol}</b></td>
                    ${unitsTd}
                    ${priceTd}
                    <td data-sort="${a.stop_loss || 0}">${a.stop_loss ? '&#8377;' + parseFloat(a.stop_loss).toFixed(2) : '-'}</td>
                    <td data-sort="${a.hard_sl_price || 0}" style="color:var(--danger); font-weight:600;">${a.hard_sl_price ? '&#8377;' + parseFloat(a.hard_sl_price).toFixed(2) : '-'}</td>
                    <td data-sort="${a.status}">${a.status}</td>
                    <td style="font-size:0.8rem; color:#aaa;">${a.reason || ''}</td>
                    <td class="text-center">${actionBtn}</td>
                </tr>`;
            });
            hideLoading();
            makeTableSortable('#actions-table', { searching: true });

            // Initial projection calc
            updateProjection();
        }

        function updateProjection(changedActionId = null) {
            if (!window._actionsData || window._actionsData.length === 0) {
                document.getElementById('cash-projections-panel').style.display = 'none';
                return;
            }

            // Show panel
            document.getElementById('cash-projections-panel').style.display = 'block';

            let estSells = 0;
            let estBuys = 0;

            window._actionsData.forEach(a => {
                if (a.status !== 'Pending' && a.status !== 'Approved') return;

                let units = a.units || 0;
                let price = parseFloat(a.execution_price || a.prev_close || 0);

                // If Pending, check if user modified inline inputs
                if (a.status === 'Pending') {
                    const uInput = document.getElementById(`units-${a.action_id}`);
                    const pInput = document.getElementById(`price-${a.action_id}`);
                    if (uInput) units = parseInt(uInput.value) || 0;
                    if (pInput) price = parseFloat(pInput.value) || 0;
                }

                const val = units * price;
                if (a.type === 'sell') estSells += val;
                if (a.type === 'buy') estBuys += val;
                // For 'swap', normally there's a sell leg and a buy leg separate. 
                // If it's a single swap action covering both conceptually, sum accordingly, but in backend swap generates buy/sell pairs.
            });

            const fmt = v => '₹' + v.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 });

            const finalCash = window._baseCash + estSells - estBuys;

            document.getElementById('proj-avail-cash').innerText = fmt(window._baseCash);
            document.getElementById('proj-est-sells').innerText = fmt(estSells);
            document.getElementById('proj-est-buys').innerText = fmt(estBuys);

            const finalEl = document.getElementById('proj-final-cash');
            finalEl.innerText = fmt(finalCash);
            finalEl.style.color = finalCash < 0 ? 'var(--danger)' : 'white';
        }

        async function confirmInlineApprove(actionId, symbol) {
            const uInput = document.getElementById(`units-${actionId}`);
            const pInput = document.getElementById(`price-${actionId}`);
            const units = uInput ? parseInt(uInput.value) : 0;
            const price = pInput ? parseFloat(pInput.value) : 0;

            if (!units || !price) {
                alert('Please enter valid units and execution price.');
                return;
            }

            if (!confirm(`Approve ${symbol} for ${units} units @ ₹${price}?`)) return;

            await fetch(`/api/v1/actions/${actionId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ status: 'Approved', units: units, execution_price: price.toString() })
            });
            loadActions();
        }

        async function updateAction(id, status) {
            await fetch(`/api/v1/actions/${id}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ status: status })
            });
            loadActions();
        }

        async function approveAll() {
            const date = document.getElementById('actions-date').value;
            if (!confirm('Approve all pending actions for ' + date + '?')) return;

            await fetch(`/api/v1/actions/approve?date=${date}&config_name=momentum_config`, { method: 'POST' });
            loadActions();
        }

        async function rejectPending() {
            if (!confirm('Reject ALL pending actions? This cannot be undone.')) return;
            try {
                const res = await fetch('/api/v1/actions/reject-all', { method: 'POST' });
                const data = await res.json();
                if (!res.ok) throw new Error(data.message || 'Reject failed');
                alert(data.message);
                loadActions();
            } catch (e) {
                alert('Error: ' + e.message);
            }
        }

        async function processActions() {
            const date = document.getElementById('actions-date').value;
            if (!confirm('Process all APPROVED actions into holdings for ' + date + '?')) return;

            await fetch(`/api/v1/actions/process?date=${date}`, { method: 'POST' });
            alert('Processing complete. Check Portfolio.');
            loadActions();
        }

        // --- APPROVE MODAL ---
        function openApproveModal(actionId, symbol, units, price) {
            document.getElementById('approve-action-id').value = actionId;
            document.getElementById('approve-symbol').value = symbol;
            document.getElementById('approve-units').value = units;
            document.getElementById('approve-price').value = price;
            document.getElementById('approve-modal-title').innerText = 'Approve: ' + symbol;
            document.getElementById('approve-modal').classList.remove('hidden');
        }

        function closeApproveModal() {
            document.getElementById('approve-modal').classList.add('hidden');
        }

        async function confirmApprove() {
            const actionId = document.getElementById('approve-action-id').value;
            const units = parseInt(document.getElementById('approve-units').value);
            const price = parseFloat(document.getElementById('approve-price').value);

            if (!units || !price) {
                alert('Please enter valid units and execution price.');
                return;
            }

            await fetch(`/api/v1/actions/${actionId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ status: 'Approved', units: units, execution_price: price.toString() })
            });
            closeApproveModal();
            loadActions();
        }

        // --- EQUITY CURVE & DRAWDOWN ---
        let equityChartInstance = null;
        let drawdownChartInstance = null;

        async function loadEquityCurve() {
            try {
                const res = await fetch('/api/v1/investment/summary/history');
                const data = await res.json();
                if (!data || !data.length) return;

                const labels = data.map(d => d.date);
                const values = data.map(d => parseFloat(d.portfolio_value || 0));

                // Compute drawdown
                let peak = values[0];
                const drawdowns = values.map(v => {
                    if (v > peak) peak = v;
                    return peak > 0 ? ((v - peak) / peak) * 100 : 0;
                });

                // Equity Curve
                const eqCtx = document.getElementById('equityCurveChart').getContext('2d');
                if (equityChartInstance) equityChartInstance.destroy();

                const gradient = eqCtx.createLinearGradient(0, 0, 0, 280);
                gradient.addColorStop(0, 'rgba(0, 200, 150, 0.3)');
                gradient.addColorStop(1, 'rgba(0, 200, 150, 0.02)');

                equityChartInstance = new Chart(eqCtx, {
                    type: 'line',
                    data: {
                        labels: labels,
                        datasets: [{
                            label: 'Portfolio Value',
                            data: values,
                            borderColor: '#00c896',
                            backgroundColor: gradient,
                            fill: true,
                            tension: 0.3,
                            pointRadius: 2,
                            pointHoverRadius: 5,
                            borderWidth: 2
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: { legend: { display: false } },
                        scales: {
                            x: { display: true, ticks: { maxTicksLimit: 8, color: '#888' }, grid: { display: false } },
                            y: { display: true, ticks: { color: '#888', callback: v => '₹' + (v / 1000).toFixed(0) + 'K' }, grid: { color: 'rgba(255,255,255,0.05)' } }
                        }
                    }
                });

                // Drawdown Chart
                const ddCtx = document.getElementById('drawdownChart').getContext('2d');
                if (drawdownChartInstance) drawdownChartInstance.destroy();

                const ddGradient = ddCtx.createLinearGradient(0, 0, 0, 280);
                ddGradient.addColorStop(0, 'rgba(255, 75, 75, 0.02)');
                ddGradient.addColorStop(1, 'rgba(255, 75, 75, 0.25)');

                drawdownChartInstance = new Chart(ddCtx, {
                    type: 'line',
                    data: {
                        labels: labels,
                        datasets: [{
                            label: 'Drawdown %',
                            data: drawdowns,
                            borderColor: '#ff4b4b',
                            backgroundColor: ddGradient,
                            fill: true,
                            tension: 0.3,
                            pointRadius: 2,
                            pointHoverRadius: 5,
                            borderWidth: 2
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: { legend: { display: false } },
                        scales: {
                            x: { display: true, ticks: { maxTicksLimit: 8, color: '#888' }, grid: { display: false } },
                            y: { display: true, ticks: { color: '#888', callback: v => v.toFixed(1) + '%' }, grid: { color: 'rgba(255,255,255,0.05)' } }
                        }
                    }
                });
            } catch (e) {
                console.error('Equity curve error:', e);
            }
        }

        // --- TRADE JOURNAL ---
        async function loadTradeJournal() {
            try {
                const res = await fetch('/api/v1/investment/trade-journal');
                const trades = await res.json();
                destroyDataTable('#journal-table');
                const tbody = document.getElementById('journal-body');
                tbody.innerHTML = '';

                if (!trades || !trades.length) {
                    tbody.innerHTML = '<tr><td colspan="10" class="text-center" style="padding:20px;">No closed trades yet</td></tr>';
                    makeTableSortable('#journal-table');
                    return;
                }

                trades.forEach(t => {
                    const pnlClass = t.pnl >= 0 ? 'pos-val' : 'neg-val';
                    tbody.innerHTML += `<tr>
                        <td data-sort="${t.entry_date}">${t.entry_date}</td>
                        <td data-sort="${t.exit_date}">${t.exit_date}</td>
                        <td><b>${t.symbol}</b></td>
                        <td data-sort="${t.units}">${t.units}</td>
                        <td class="text-right" data-sort="${t.entry_price}">₹${t.entry_price.toFixed(2)}</td>
                        <td class="text-right" data-sort="${t.exit_price}">₹${t.exit_price.toFixed(2)}</td>
                        <td class="text-right ${pnlClass}" data-sort="${t.pnl}">₹${t.pnl.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
                        <td class="text-right ${pnlClass}" data-sort="${t.return_pct}">${t.return_pct.toFixed(2)}%</td>
                        <td data-sort="${t.days_held}">${t.days_held}</td>
                        <td style="font-size:0.8rem;color:#aaa;">${t.reason}</td>
                    </tr>`;
                });
                makeTableSortable('#journal-table', { searching: true, paging: true, pageLength: 15, info: true, order: [[1, 'desc']] });
            } catch (e) {
                console.error('Trade journal error:', e);
                document.getElementById('journal-body').innerHTML = '<tr><td colspan="10" class="text-center">Failed to load</td></tr>';
            }
        }

        // --- CONFIG ---
        async function loadConfig() {
            const name = document.getElementById('config-select').value;
            const res = await fetch(`/api/v1/config/${name}`);
            const data = await res.json();

            document.getElementById('conf-initial').value = data.initial_capital;
            document.getElementById('conf-risk').value = data.risk_threshold;
            document.getElementById('conf-max').value = data.max_positions;
            document.getElementById('conf-min').value = data.min_position_percent;
            document.getElementById('conf-exit').value = data.exit_threshold;
            document.getElementById('conf-sl-mult').value = data.sl_multiplier;
            document.getElementById('conf-sl-step').value = data.sl_step_percent ?? '';
            document.getElementById('conf-buffer').value = data.buffer_percent;
            document.getElementById('conf-hard-sl').value = data.hard_sl_percent ?? 0.03;
        }

        async function saveConfig() {
            const name = document.getElementById('config-select').value;
            const payload = {
                initial_capital: parseFloat(document.getElementById('conf-initial').value),
                risk_threshold: parseFloat(document.getElementById('conf-risk').value),
                max_positions: parseInt(document.getElementById('conf-max').value),
                min_position_percent: parseFloat(document.getElementById('conf-min').value),
                exit_threshold: parseFloat(document.getElementById('conf-exit').value),
                sl_multiplier: parseFloat(document.getElementById('conf-sl-mult').value),
                buffer_percent: parseFloat(document.getElementById('conf-buffer').value),
                hard_sl_percent: parseFloat(document.getElementById('conf-hard-sl').value),
            };

            await fetch(`/api/v1/config/${name}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            alert('Configuration Saved!');
        }

        // --- BACKTEST ---
        function initBacktestDates() {
            const today = new Date();
            const start = new Date();
            start.setFullYear(today.getFullYear() - 1);
            document.getElementById('bt-start').value = start.toISOString().split('T')[0];
            document.getElementById('bt-end').value = today.toISOString().split('T')[0];
        }

        let backtestChartInstance = null;

        async function runBacktest() {
            const label = document.getElementById('bt-label').value.trim();
            const payload = {
                start_date: document.getElementById('bt-start').value,
                end_date: document.getElementById('bt-end').value,
                config_name: document.getElementById('bt-config').value,
                check_daily_sl: document.getElementById('bt-daily-sl').checked,
                mid_week_buy: document.getElementById('bt-mid-week').checked,
                enable_pyramiding: document.getElementById('bt-pyramid').checked
            };
            if (label) payload.run_label = label;

            showLoading('Running Backtest... (this takes time)');
            try {
                const res = await fetch('/api/v1/backtest/run', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });

                const data = await res.json();

                if (res.ok) {
                    populateBacktestResults(data);
                    // Refresh history list since a new run was saved
                    loadBacktestHistory();
                } else {
                    alert('Backtest Failed: ' + data.message);
                }

            } catch (e) { console.error(e); alert('Error running backtest'); }
            hideLoading();
        }

        function populateBacktestResults(data) {
            document.getElementById('bt-results').classList.remove('hidden');

            const sum = data.summary || {};

            document.getElementById('bt-return').innerText = (sum.total_return || 0).toFixed(2) + '%';
            document.getElementById('bt-sharpe').innerText = (sum.sharpe_ratio || 0).toFixed(2);
            document.getElementById('bt-dd').innerText = (sum.max_drawdown || 0).toFixed(2) + '%';
            document.getElementById('bt-winrate').innerText = (sum.win_rate || 0).toFixed(2) + '%';

            document.getElementById('bt-costs').innerText = '₹' + (sum.total_transaction_costs || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
            document.getElementById('bt-tax').innerText = '₹' + (sum.total_tax || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

            const netRetPct = sum.net_post_tax_return_pct || 0;
            const netRetAbs = sum.net_post_tax_return || 0;
            document.getElementById('bt-net-ret').innerText = `₹${netRetAbs.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} (${netRetPct.toFixed(2)}%)`;

            const grossGain = (sum.final_value || 0) - (sum.initial_capital || 0);
            let eff = 0;
            if (grossGain > 0) {
                eff = (netRetAbs / grossGain) * 100;
            }
            document.getElementById('bt-efficiency').innerText = eff.toFixed(1) + '% retained';

            // Render YoY Returns
            destroyDataTable('#bt-yoy-table');
            const yoyBody = document.getElementById('bt-yoy-body');
            yoyBody.innerHTML = '';
            if (sum.yearly_returns && sum.yearly_returns.length > 0) {
                document.getElementById('bt-yoy-card').classList.remove('hidden');
                sum.yearly_returns.forEach(y => {
                    const retClass = y.return_pct >= 0 ? 'pos-val' : 'neg-val';
                    const tr = `<tr>
                        <td><strong>${y.year}</strong></td>
                        <td class="text-right ${retClass}">${y.return_pct.toFixed(2)}%</td>
                        <td class="text-right ${retClass}">₹${y.pnl.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
                        <td class="text-right">₹${y.end_value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
                    </tr>`;
                    yoyBody.innerHTML += tr;
                });
                makeTableSortable('#bt-yoy-table', { searching: false, paging: false, order: [[0, 'asc']] });
            } else {
                document.getElementById('bt-yoy-card').classList.add('hidden');
            }

            // Render Chart
            renderEquityChart(data.equity_curve || []);

            // Render Trades
            destroyDataTable('#bt-trades-table');
            const tbody = document.getElementById('bt-trades-body');
            tbody.innerHTML = '';
            const trades = data.trades || [];
            const sellTrades = trades.filter(t => t.type === 'SELL');

            sellTrades.forEach(t => {
                const investedValue = (t.price || 0) * (t.units || 1);
                const retPct = investedValue > 0 ? ((t.pnl / investedValue) * 100).toFixed(2) : '0.00';
                const tr = `<tr>
                    <td>${t.symbol}</td>
                    <td data-sort="${t.type}">${t.type}</td>
                    <td data-sort="${t.entry_date}">${t.entry_date}</td>
                    <td data-sort="${t.exit_date}">${t.exit_date}</td>
                    <td class="text-right ${t.pnl >= 0 ? 'pos-val' : 'neg-val'}" data-sort="${t.pnl}">${t.pnl.toFixed(2)}</td>
                    <td class="text-right" data-sort="${retPct}">${retPct}%</td>
                </tr>`;
                tbody.innerHTML += tr;
            });
            makeTableSortable('#bt-trades-table', { searching: true, paging: true, pageLength: 10, info: true });

            // Render Open Positions at Backtest End
            destroyDataTable('#bt-open-positions-table');
            const openBody = document.getElementById('bt-open-positions-body');
            openBody.innerHTML = '';
            const openPositions = sum.open_positions || [];
            if (openPositions.length > 0) {
                document.getElementById('bt-open-positions-card').classList.remove('hidden');
                openPositions.forEach(p => {
                    const pnlClass = p.unrealized_pnl >= 0 ? 'pos-val' : 'neg-val';
                    const tr = `<tr>
                        <td><b>${p.symbol}</b></td>
                        <td data-sort="${p.entry_date}">${p.entry_date}</td>
                        <td class="text-right" data-sort="${p.units}">${p.units}</td>
                        <td class="text-right">₹${p.avg_price.toFixed(2)}</td>
                        <td class="text-right">₹${p.current_price.toFixed(2)}</td>
                        <td class="text-right" data-sort="${p.market_value}">₹${p.market_value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
                        <td class="text-right ${pnlClass}" data-sort="${p.unrealized_pnl}">₹${p.unrealized_pnl.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
                    </tr>`;
                    openBody.innerHTML += tr;
                });
                makeTableSortable('#bt-open-positions-table', { searching: false, order: [[5, 'desc']] });
            } else {
                document.getElementById('bt-open-positions-card').classList.add('hidden');
            }

            // Raw log
            document.getElementById('bt-raw-log').innerText = data.report_text || '';
        }

        // --- BACKTEST HISTORY ---
        async function loadBacktestHistory() {
            try {
                const res = await fetch('/api/v1/backtest/history');
                const runs = await res.json();
                destroyDataTable('#bt-history-table');
                const tbody = document.getElementById('bt-history-body');
                tbody.innerHTML = '';

                if (!runs || !runs.length) {
                    tbody.innerHTML = '<tr><td colspan="11" class="text-center">No saved runs</td></tr>';
                    makeTableSortable('#bt-history-table');
                    return;
                }

                runs.forEach((r, i) => {
                    const retClass = (r.total_return || 0) >= 0 ? 'pos-val' : 'neg-val';
                    const ddVal = r.max_drawdown != null ? r.max_drawdown.toFixed(2) : '-';
                    const sharpeVal = r.sharpe_ratio != null ? r.sharpe_ratio.toFixed(2) : '-';
                    const retVal = r.total_return != null ? r.total_return.toFixed(2) : '-';
                    const created = r.created_at ? r.created_at.substring(0, 16).replace('T', ' ') : '-';
                    const dailySl = r.check_daily_sl ? '✓' : '✗';
                    const mwb = r.mid_week_buy ? '✓' : '✗';

                    tbody.innerHTML += `<tr>
                        <td data-sort="${r.id}">${r.id}</td>
                        <td>${r.run_label || '<em style="color:#666;">—</em>'}</td>
                        <td data-sort="${r.config_name}">${r.config_name || '-'}</td>
                        <td style="white-space:nowrap;" data-sort="${r.start_date}">${r.start_date} → ${r.end_date}</td>
                        <td class="text-center" data-sort="${r.check_daily_sl}">${dailySl}</td>
                        <td class="text-center" data-sort="${r.mid_week_buy}">${mwb}</td>
                        <td class="text-right ${retClass}" data-sort="${r.total_return}">${retVal}%</td>
                        <td class="text-right" style="color:var(--danger);" data-sort="${r.max_drawdown}">${ddVal}%</td>
                        <td class="text-right" data-sort="${r.sharpe_ratio}">${sharpeVal}</td>
                        <td style="font-size:0.8rem; color:#888;" data-sort="${r.created_at}">${created}</td>
                        <td class="text-center" style="white-space:nowrap;">
                            <button class="badge badge-buy" style="border:none; cursor:pointer; margin-right:4px;" onclick="loadBacktestRun(${r.id})">Load</button>
                            <button class="badge badge-sell" style="border:none; cursor:pointer;" onclick="deleteBacktestRun(${r.id})">Del</button>
                        </td>
                    </tr>`;
                });
                makeTableSortable('#bt-history-table', { searching: false, order: [[0, 'desc']] });
            } catch (e) {
                console.error('Failed to load backtest history:', e);
            }
        }

        async function loadBacktestRun(runId) {
            showLoading('Loading backtest run...');
            try {
                const res = await fetch(`/api/v1/backtest/history/${runId}`);
                const data = await res.json();
                if (res.ok) {
                    populateBacktestResults(data);
                    // Scroll to results
                    document.getElementById('bt-results').scrollIntoView({ behavior: 'smooth' });
                } else {
                    alert('Failed to load run: ' + (data.message || 'Unknown error'));
                }
            } catch (e) {
                console.error(e);
                alert('Error loading backtest run');
            }
            hideLoading();
        }

        async function deleteBacktestRun(runId) {
            if (!confirm('Delete this backtest run? This will also remove the data files.')) return;
            try {
                const res = await fetch(`/api/v1/backtest/history/${runId}`, { method: 'DELETE' });
                const data = await res.json();
                if (res.ok) {
                    loadBacktestHistory();
                } else {
                    alert('Failed to delete: ' + (data.message || 'Unknown error'));
                }
            } catch (e) {
                console.error(e);
                alert('Error deleting backtest run');
            }
        }

        function renderEquityChart(equityCurve) {
            const ctx = document.getElementById('equityChart').getContext('2d');

            if (backtestChartInstance) {
                backtestChartInstance.destroy();
            }

            // equityCurve is [{date, value}, ...] from the API
            const labels = equityCurve.map(p => p.date || '');
            const values = equityCurve.map(p => p.value);

            backtestChartInstance = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: labels,
                    datasets: [{
                        label: 'Portfolio Equity',
                        data: values,
                        borderColor: '#3b82f6',
                        backgroundColor: 'rgba(59, 130, 246, 0.1)',
                        tension: 0.1,
                        fill: true
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false }
                    },
                    scales: {
                        x: {
                            display: true,
                            ticks: { maxTicksLimit: 8, color: '#94a3b8' },
                            grid: { display: false }
                        },
                        y: {
                            grid: { color: '#2d3748' },
                            ticks: { color: '#94a3b8' }
                        }
                    }
                }
            });
        }

        async function refreshPortfolio() {
            // Always sync latest
            showLoading('Syncing Prices...');
            try {
                const res = await fetch('/api/v1/investment/sync-prices', { method: 'POST' });
                const dat = await res.json();
                if (!res.ok) throw new Error(dat.message);
                console.log("Sync complete:", dat.message);
            } catch (e) {
                console.error("Failed to sync prices", e);
            }
            await loadPortfolio();
            hideLoading();
        }

        // --- LIVE PRICE STREAMING ---
        let _liveInterval = null;
        let _isLive = false;

        // Live PnL Chart vars
        let livePnlChartInstance = null;
        let livePnlLabels = [];
        let livePnlData = [];

        function initLivePnlChart() {
            const ctx = document.getElementById('livePnlChart').getContext('2d');
            if (livePnlChartInstance) return;

            livePnlChartInstance = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: livePnlLabels,
                    datasets: [{
                        label: "Today's P&L",
                        data: livePnlData,
                        borderColor: '#fbbf24',
                        backgroundColor: 'rgba(251, 191, 36, 0.1)',
                        tension: 0.3,
                        fill: true,
                        pointRadius: 2,
                        pointHoverRadius: 4,
                        borderWidth: 2
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: { legend: { display: false } },
                    scales: {
                        x: { display: true, ticks: { maxTicksLimit: 10, color: '#888' }, grid: { display: false } },
                        y: { display: true, ticks: { color: '#888' }, grid: { color: 'rgba(255,255,255,0.05)' } }
                    },
                    animation: { duration: 0 }
                }
            });
        }

        async function toggleLiveStream() {
            if (_isLive) {
                stopLiveStream();
            } else {
                await startLiveStream();
            }
        }

        async function startLiveStream() {
            const btn = document.getElementById('live-toggle-btn');
            const label = document.getElementById('live-status-label');
            btn.innerText = '⏳ Starting...';
            btn.disabled = true;

            try {
                const res = await fetch('/api/v1/investment/start-ticker', { method: 'POST' });
                const data = await res.json();
                if (!res.ok) {
                    alert('Failed to start ticker: ' + (data.message || 'Unknown error'));
                    btn.innerText = '📡 Go Live';
                    btn.disabled = false;
                    return;
                }

                _isLive = true;
                btn.innerText = '⏸ Stop Live';
                btn.style.background = 'var(--danger)';
                btn.disabled = false;
                label.innerText = '🟢 Streaming live';
                label.style.color = 'var(--accent)';

                // Initialize live chart
                livePnlLabels = [];
                livePnlData = [];
                document.getElementById('live-pnl-card').style.display = 'block';
                initLivePnlChart();
                livePnlChartInstance.update();

                // Start polling every 30 seconds
                pollLivePrices(); // immediate first poll
                _liveInterval = setInterval(pollLivePrices, 30000);

            } catch (e) {
                console.error('Start live error:', e);
                btn.innerText = '📡 Go Live';
                btn.disabled = false;
            }
        }

        function stopLiveStream() {
            if (_liveInterval) {
                clearInterval(_liveInterval);
                _liveInterval = null;
            }
            _isLive = false;

            const btn = document.getElementById('live-toggle-btn');
            btn.innerText = '📡 Go Live';
            btn.style.background = 'var(--accent)';

            const label = document.getElementById('live-status-label');
            label.innerText = '⏸ Not streaming';
            label.style.color = 'var(--text-muted)';

            // Fire-and-forget stop
            fetch('/api/v1/investment/stop-ticker', { method: 'POST' }).catch(() => { });
        }

        async function pollLivePrices() {
            try {
                const res = await fetch('/api/v1/investment/live-prices');
                const data = await res.json();
                if (!data.prices) return;

                const prices = data.prices;
                const rows = document.querySelectorAll('#holdings-body tr[data-symbol]');
                let totalDayPnl = 0;
                let totalVal = 0;
                let totalPnl = 0;

                const dt = $('#holdings-table').DataTable();

                rows.forEach(row => {
                    const sym = row.getAttribute('data-symbol');

                    const p = prices[sym] || prices[sym + '-BE'];
                    if (!p || !p.last_price) return;

                    const units = parseFloat(row.children[2].getAttribute('data-sort') || 0);
                    const avgPrice = parseFloat(row.children[3].getAttribute('data-sort') || 0);
                    const ltp = p.last_price;
                    const prevClose = p.prev_close || 0;

                    const newVal = ltp * units;
                    const inv = avgPrice * units;
                    const pnl = newVal - inv;
                    const pnlPct = inv !== 0 ? (pnl / inv) * 100 : 0;
                    const dayPnl = (ltp - prevClose) * units;

                    totalVal += newVal;
                    totalPnl += pnl;
                    totalDayPnl += dayPnl;

                    // Update cells using DataTables API to preserve sorting
                    // Columns: Symbol(0), Entry Date(1), Units(2), Avg Price(3), Current(4), SL(5), Hard SL(6), Cap Risk(7), Invested(8), Value(9), Unrealized P&L(10), %(11), Day P&L(12)

                    const dtRow = dt.row(row);

                    // Helper to update text and sorting value
                    function updateCell(colIdx, sortVal, htmlStr) {
                        const cell = dt.cell(dtRow, colIdx);
                        const node = cell.node();
                        if (node) {
                            node.setAttribute('data-sort', sortVal);
                            node.innerHTML = htmlStr;
                        }
                        cell.invalidate('dom'); // Tell DataTables to re-read the data-sort and text from DOM
                    }

                    // Col 4: Current Price
                    updateCell(4, ltp, `₹${ltp.toFixed(2)}`);

                    // Col 9: Value
                    updateCell(9, newVal, `₹${newVal.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`);

                    // Col 10: Unrealized P&L
                    const pnlClass = pnl >= 0 ? 'pos-val' : 'neg-val';
                    updateCell(10, pnl, `<span class="${pnlClass}">₹${pnl.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>`);

                    // Col 11: %
                    const pnlPctClass = pnlPct >= 0 ? 'pos-val' : 'neg-val';
                    updateCell(11, pnlPct, `<span class="${pnlPctClass}">${pnlPct.toFixed(2)}%</span>`);

                    // Col 12: Day P&L
                    const dayPnlClass = dayPnl >= 0 ? 'pos-val' : 'neg-val';
                    updateCell(12, dayPnl, `<span class="${dayPnlClass}">₹${dayPnl.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>`);
                });

                // Redraw table to apply sorting/filtering updates without resetting pagination
                dt.draw(false);

                // Update footer totals
                const totalValEl = document.getElementById('live-total-val');
                if (totalValEl) totalValEl.innerHTML = `₹${totalVal.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

                const totalPnlEl = document.getElementById('live-total-pnl');
                if (totalPnlEl) {
                    totalPnlEl.className = `text-center ${totalPnl >= 0 ? 'pos-val' : 'neg-val'}`;
                    totalPnlEl.innerHTML = `₹${totalPnl.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
                }

                const totalDayEl = document.getElementById('live-total-day-pnl');
                if (totalDayEl) {
                    totalDayEl.style.color = '';  // clear inline style so class colors apply
                    totalDayEl.className = `text-center ${totalDayPnl >= 0 ? 'pos-val' : 'neg-val'}`;
                    totalDayEl.innerHTML = `₹${totalDayPnl.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
                }

                // Update summary card
                const dayPnlCard = document.getElementById('sum-day-pnl');
                if (dayPnlCard) {
                    dayPnlCard.className = `metric-value ${totalDayPnl >= 0 ? 'pos-val' : 'neg-val'}`;
                    dayPnlCard.innerText = `₹${totalDayPnl.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
                }

                // Update live chart
                if (livePnlChartInstance) {
                    const now = new Date();
                    const timeStr = String(now.getHours()).padStart(2, '0') + ':' +
                        String(now.getMinutes()).padStart(2, '0') + ':' +
                        String(now.getSeconds()).padStart(2, '0');
                    livePnlLabels.push(timeStr);
                    livePnlData.push(totalDayPnl);

                    if (livePnlLabels.length > 120) { // keep last 1 hour of points at 30s interval
                        livePnlLabels.shift();
                        livePnlData.shift();
                    }

                    livePnlChartInstance.data.datasets[0].borderColor = totalDayPnl >= 0 ? '#10b981' : '#ef4444';
                    livePnlChartInstance.data.datasets[0].backgroundColor = totalDayPnl >= 0 ? 'rgba(16, 185, 129, 0.1)' : 'rgba(239, 68, 68, 0.1)';
                    livePnlChartInstance.update();
                }

                // Update portfolio value card too
                const valCard = document.getElementById('sum-val');
                if (valCard && totalVal > 0) {
                    const cashCard = document.getElementById('sum-cash');
                    let cashVal = 0;
                    if (cashCard && cashCard.innerText) {
                        cashVal = parseFloat(cashCard.innerText.replace(/[^0-9.-]+/g, '')) || 0;
                    }
                    valCard.innerText = `₹${(totalVal + cashVal).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
                }

                // Update unrealized PnL card
                const unrealizedCard = document.getElementById('sum-unrealized');
                if (unrealizedCard) {
                    unrealizedCard.className = `metric-value ${totalPnl >= 0 ? 'pos-val' : 'neg-val'}`;
                    unrealizedCard.innerText = `₹${totalPnl.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
                }

            } catch (e) {
                console.error('Poll live prices error:', e);
            }
        }
// ── Live clock ──────────────────────────────────────────────
(function startClock() {
    function tick() {
        const now = new Date();
        const t = now.toLocaleTimeString('en-IN', { hour12: false });
        const d = now.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' });
        const te = document.getElementById('hdr-time');
        const de = document.getElementById('hdr-date');
        if (te) te.textContent = t;
        if (de) de.textContent = d;
    }
    tick();
    setInterval(tick, 1000);
})();
