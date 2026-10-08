(() => {
  const host = document.getElementById("index-carousel");
  if (!host) return;
  const status = document.getElementById("index-feed-status");
  const symbols = ["NIFTY 50", "NIFTY 100", "NIFTY BANK", "SENSEX"];
  const fmt = value => new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(Number(value));
  let loading = false, initialized = false;
  const groups = [false, true].map(copy => {
    const group = document.createElement("div"); group.className = "market-ticker-group";
    group.dataset.copy = String(copy);
    if (copy) group.setAttribute("aria-hidden", "true");
    host.append(group); return group;
  });
  const viewport = host.parentElement;
  const sizeTrack = () => host.style.setProperty("--ticker-width", `${viewport.clientWidth}px`);
  const observer = typeof ResizeObserver !== "undefined" ? new ResizeObserver(sizeTrack) : null;
  observer?.observe(viewport); sizeTrack();
  function render(quotes) {
    const bySymbol = new Map(quotes.map(q => [q.symbol, q]));
    for (const group of groups) {
    for (const symbol of symbols) {
      let tile = [...group.children].find(node => node.dataset.symbol === symbol);
      if (!tile) {
        tile = document.createElement("article"); tile.className = "market-index"; tile.dataset.symbol = symbol;
        const name = document.createElement("span"); name.className = "index-symbol"; name.textContent = symbol;
        const price = document.createElement("strong"), change = document.createElement("span"); change.className = "index-change";
        tile.append(name, price, change); group.append(tile);
      }
      const quote = bySymbol.get(symbol), price = tile.querySelector("strong"), change = tile.querySelector(".index-change");
      price.textContent = quote ? fmt(quote.last_price) : "—";
      change.textContent = quote ? `${Number(quote.change_percent) >= 0 ? "▲" : "▼"} ${Math.abs(Number(quote.change_percent)).toFixed(2)}%` : "—";
      change.className = quote ? `index-change ${Number(quote.change_percent) >= 0 ? "positive" : "negative"}` : "index-change subtle";
      tile.title = quote ? `Observed ${new Date(quote.observed_at).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" })} IST · ${quote.freshness.toLowerCase()}` : "No stored quote";
    }
    }
    status.textContent = quotes.some(q => q.freshness === "FRESH") ? "Live Kite quotes" : quotes.length ? "Last available quotes" : "Waiting for market login";
    status.parentElement.title = status.textContent;
    status.parentElement.dataset.live = String(quotes.some(q => q.freshness === "FRESH"));
  }
  async function load() {
    if (loading || document.hidden) return;
    loading = true;
    try { render((await Screener.api("/api/market/indices/quotes")).quotes); }
    catch { status.textContent = "Quotes unavailable"; status.parentElement.title = status.textContent; status.parentElement.dataset.live = "false"; }
    finally { loading = false; }
  }
  async function startPolling(state) {
    if (state?.status !== "ACTIVE" || initialized) return;
    initialized = true;
    try {
      await Screener.api("/api/market/indices/poller", { method: "POST", body: JSON.stringify({ action: "start" }) });
      await Screener.api("/api/market/indices/poller", { method: "POST", body: JSON.stringify({ action: "tick" }) });
      await load();
    } catch { initialized = false; status.textContent = "Quote refresh unavailable"; }
  }
  window.addEventListener("market-session", event => startPolling(event.detail));
  startPolling(window.marketSessionStatus);
  render([]); load();
  const quoteTimer = setInterval(load, 30000);
  window.addEventListener("pagehide", () => { clearInterval(quoteTimer); observer?.disconnect(); });
})();
