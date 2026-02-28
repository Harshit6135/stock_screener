import re
import os

filepath = 'templates/dashboard.html'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. CSS
css_old = """        .text-right {
            text-align: right;
        }

        .text-center {
            text-align: center;
        }"""
css_new = """        .text-right {
            text-align: right !important;
        }

        .text-center {
            text-align: center !important;
        }"""
if css_old in content:
    content = content.replace(css_old, css_new)
    print("Replaced CSS")
else:
    print("Could not find CSS")

# 2. Holdings Table Headers
th_old = """                        <tr>
                            <th>Symbol</th>
                            <th class="text-center">Entry Date</th>
                            <th class="text-center">Units</th>
                            <th class="text-center">Avg Price</th>
                            <th class="text-center">Current</th>
                            <th class="text-center">SL</th>
                            <th class="text-center">Invested</th>
                            <th class="text-center">Value</th>
                            <th class="text-center">Unrealized P&L</th>
                            <th class="text-center">%</th>
                            <th class="text-center">Day P&L</th>
                        </tr>"""
th_new = """                        <tr>
                            <th>Symbol</th>
                            <th class="text-center">Entry Date</th>
                            <th class="text-center">Units</th>
                            <th class="text-center">Avg Price</th>
                            <th class="text-center">Current</th>
                            <th class="text-center">SL</th>
                            <th class="text-center">Cap. Risk</th>
                            <th class="text-center">Invested</th>
                            <th class="text-center">Value</th>
                            <th class="text-center">Unrealized P&L</th>
                            <th class="text-center">%</th>
                            <th class="text-center">Day P&L</th>
                        </tr>"""
if th_old in content:
    content = content.replace(th_old, th_new)
    print("Replaced Th")
else:
    print("Could not find Th")

# 3. Live Chart HTML
html_old = """        </div>

        <!-- Trade Journal -->
        <div class="card">"""
html_new = """        </div>

        <!-- Live PnL Chart (Hidden by default) -->
        <div class="card" id="live-pnl-card" style="display:none; margin-bottom: 20px;">
            <h3>Live Today's P&L</h3>
            <div style="height:250px;">
                <canvas id="livePnlChart"></canvas>
            </div>
        </div>

        <!-- Trade Journal -->
        <div class="card">"""
if html_old in content:
    content = content.replace(html_old, html_new)
    print("Replaced HTML")
else:
    print("Could not find HTML")

# 4. renderHoldings var and row
rh_old = """            let totalInv = 0, totalVal = 0, totalPnL = 0;

            holdings.forEach(h => {
                const entryPrice = parseFloat(h.entry_price || 0);
                const avgPrice = parseFloat(h.avg_price || h.entry_price || 0);
                const currentPrice = parseFloat(h.current_price || 0);
                const currentSl = parseFloat(h.current_sl || 0);
                const units = parseFloat(h.units || 0);

                const inv = avgPrice * units;
                const val = currentPrice * units;
                const pnl = val - inv;
                const pnlPct = inv !== 0 ? (pnl / inv) * 100 : 0;

                totalInv += inv;
                totalVal += val;
                totalPnL += pnl;

                const row = `<tr data-symbol="${h.symbol}">
                    <td><strong>${h.symbol}</strong></td>
                    <td class="text-center" data-sort="${h.entry_date}">${h.entry_date}</td>
                    <td class="text-center" data-sort="${units}">${units}</td>
                    <td class="text-center" data-sort="${avgPrice}">₹${avgPrice.toFixed(2)}</td>
                    <td class="text-center live-current" data-sort="${currentPrice}">₹${currentPrice.toFixed(2)}</td>
                    <td class="text-center" data-sort="${currentSl}" style="color:var(--danger);">₹${currentSl.toFixed(2)}</td>
                    <td class="text-center" data-sort="${inv}">₹${inv.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
                    <td class="text-center live-value" data-sort="${val}">₹${val.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
                    <td class="text-center live-pnl ${pnl >= 0 ? 'pos-val' : 'neg-val'}" data-sort="${pnl}">₹${pnl.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
                    <td class="text-center live-pnlpct ${pnl >= 0 ? 'pos-val' : 'neg-val'}" data-sort="${pnlPct}">${pnlPct.toFixed(2)}%</td>
                    <td class="text-center live-day-pnl" data-sort="0" style="color:var(--text-muted);">-</td>
                </tr>`;
                tbody.innerHTML += row;
            });"""
rh_new = """            let totalInv = 0, totalVal = 0, totalPnL = 0, totalCapRisk = 0;

            holdings.forEach(h => {
                const entryPrice = parseFloat(h.entry_price || 0);
                const avgPrice = parseFloat(h.avg_price || h.entry_price || 0);
                const currentPrice = parseFloat(h.current_price || 0);
                const currentSl = parseFloat(h.current_sl || 0);
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
                    <td class="text-center" data-sort="${currentSl}" style="color:var(--danger);">₹${currentSl.toFixed(2)}</td>
                    <td class="text-center" data-sort="${capRisk}" style="color:var(--warning);">₹${currentSl > 0 ? capRisk.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '-'}</td>
                    <td class="text-center" data-sort="${inv}">₹${inv.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
                    <td class="text-center live-value" data-sort="${val}">₹${val.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
                    <td class="text-center live-pnl ${pnl >= 0 ? 'pos-val' : 'neg-val'}" data-sort="${pnl}">₹${pnl.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
                    <td class="text-center live-pnlpct ${pnl >= 0 ? 'pos-val' : 'neg-val'}" data-sort="${pnlPct}">${pnlPct.toFixed(2)}%</td>
                    <td class="text-center live-day-pnl" data-sort="0" style="color:var(--text-muted);">-</td>
                </tr>`;
                tbody.innerHTML += row;
            });"""
if rh_old in content:
    content = content.replace(rh_old, rh_new)
    print("Replaced RH")
else:
    print("Could not find RH")

# 5. renderHoldings Totals
rht_old = """            // Totals
            const totalRow = `<tr style="font-weight:700; background:#232730;">
                    <td colspan="6">TOTALS</td>
                    <td class="text-right">₹${totalInv.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
                    <td class="text-right" id="live-total-val">₹${totalVal.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
                    <td class="text-right ${totalPnL >= 0 ? 'pos-val' : 'neg-val'}" id="live-total-pnl">₹${totalPnL.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
                    <td class="text-right ${totalPnL >= 0 ? 'pos-val' : 'neg-val'}">${totalInv !== 0 ? ((totalPnL / totalInv) * 100).toFixed(2) : '0.00'}%</td>
                    <td class="text-right" id="live-total-day-pnl" style="color:var(--text-muted);">-</td>
                </tr>`;"""
rht_new = """            // Totals
            const totalRow = `<tr style="font-weight:700; background:#232730;">
                    <td colspan="6">TOTALS</td>
                    <td class="text-right" style="color:var(--warning);">₹${totalCapRisk.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
                    <td class="text-right">₹${totalInv.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
                    <td class="text-right" id="live-total-val">₹${totalVal.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
                    <td class="text-right ${totalPnL >= 0 ? 'pos-val' : 'neg-val'}" id="live-total-pnl">₹${totalPnL.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
                    <td class="text-right ${totalPnL >= 0 ? 'pos-val' : 'neg-val'}">${totalInv !== 0 ? ((totalPnL / totalInv) * 100).toFixed(2) : '0.00'}%</td>
                    <td class="text-right" id="live-total-day-pnl" style="color:var(--text-muted);">-</td>
                </tr>`;"""
if rht_old in content:
    content = content.replace(rht_old, rht_new)
    print("Replaced RHT")
else:
    print("Could not find RHT")

# 6. Live Streaming Start/Init
ls_old = """        // --- LIVE PRICE STREAMING ---
        let _liveInterval = null;
        let _isLive = false;

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

                // Start polling every 2 seconds
                pollLivePrices(); // immediate first poll
                _liveInterval = setInterval(pollLivePrices, 30000);"""
ls_new = """        // --- LIVE PRICE STREAMING ---
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
                _liveInterval = setInterval(pollLivePrices, 30000);"""
if ls_old in content:
    content = content.replace(ls_old, ls_new)
    print("Replaced LS")
else:
    print("Could not find LS")

# 7. Update Live Chart in pollLivePrices
ulp_old = """                // Update summary card
                const dayPnlCard = document.getElementById('sum-day-pnl');
                if (dayPnlCard) {
                    dayPnlCard.className = `metric-value ${totalDayPnl >= 0 ? 'pos-val' : 'neg-val'}`;
                    dayPnlCard.innerText = `₹${totalDayPnl.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
                }

                // Update portfolio value card too
                const valCard = document.getElementById('sum-val');
                if (valCard && totalVal > 0) {
                    valCard.innerText = `₹${totalVal.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
                }"""
ulp_new = """                // Update summary card
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
                    valCard.innerText = `₹${totalVal.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
                }"""
if ulp_old in content:
    content = content.replace(ulp_old, ulp_new)
    print("Replaced ULP")
else:
    print("Could not find ULP")

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)
print("Saved UI changes")
