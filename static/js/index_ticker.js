// ── Index Ticker (separate from portfolio WebSocket) ─────────────────────────
(function initIndexTicker() {
    const POLL_INTERVAL = 5000;     // poll prices every 5s
    const START_RETRY   = 3000;     // retry start if backend not ready
    let _pollTimer      = null;
    let _started        = false;

    // Instrument display order
    const INDEX_ORDER = ['NIFTY 50', 'NIFTY 100', 'NIFTY BANK', 'SENSEX'];

    function fmt(val) {
        return val.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }

    function buildTickerHTML(prices) {
        // Build items × 2 for seamless infinite scroll
        let items = INDEX_ORDER.map(name => {
            const d = prices[name];
            if (!d || !d.last_price) return '';
            const chg    = d.change || 0;
            const isUp   = chg >= 0;
            const arrow  = isUp ? '▲' : '▼';
            const chgCls = isUp ? 't-change-up' : 't-change-down';
            return `<span class="ticker-item">
                <span class="t-name">${name}</span>
                <span class="t-price">${fmt(d.last_price)}</span>
                <span class="${chgCls}">
                    <span class="t-arrow">${arrow}</span>${Math.abs(chg).toFixed(2)}%
                </span>
            </span>`;
        }).join('');

        // Duplicate content for seamless loop
        return items + items;
    }

    async function startIndexTicker() {
        try {
            const res  = await fetch('/api/v1/index/start', { method: 'POST' });
            const data = await res.json();
            if (data.running || res.ok) {
                _started = true;
                console.log('[Index Ticker] Started:', data.message);
                // Small delay then start polling
                setTimeout(pollIndexPrices, 1000);
                _pollTimer = setInterval(pollIndexPrices, POLL_INTERVAL);
            } else {
                console.warn('[Index Ticker] Not started yet, retrying...');
                setTimeout(startIndexTicker, START_RETRY);
            }
        } catch (e) {
            console.warn('[Index Ticker] Start failed, retrying...', e);
            setTimeout(startIndexTicker, START_RETRY);
        }
    }

    async function pollIndexPrices() {
        try {
            const res  = await fetch('/api/v1/index/prices');
            const data = await res.json();
            const prices = data.prices || {};

            // Skip render if all zeros (market closed / not streamed yet)
            const hasData = Object.values(prices).some(p => p.last_price > 0);
            const track   = document.getElementById('ticker-track');
            if (!track) return;

            if (hasData) {
                track.innerHTML = buildTickerHTML(prices);
            } else {
                track.innerHTML = '<span class="ticker-item ticker-loading">⟳ Waiting for market data...</span>';
            }
        } catch (e) {
            console.warn('[Index Ticker] Poll error:', e);
        }
    }

    // Auto-start on page load (after DOM ready)
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', startIndexTicker);
    } else {
        startIndexTicker();
    }
})();
