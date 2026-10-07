(() => {
  const host = document.getElementById("index-carousel");
  if (!host) return;
  const status = document.getElementById("index-feed-status");
  const symbols = ["NIFTY 50", "NIFTY NEXT 50", "NIFTY 500", "NIFTY MIDCAP 150", "NIFTY SMLCAP 250"];
  const fmt = value => new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 }).format(Number(value));
  let loading = false, paused = false, initialized = false;
  function render(quotes) {
    const bySymbol = new Map(quotes.map(q => [q.symbol, q]));
    for (const symbol of symbols) {
      let tile = [...host.children].find(node => node.dataset.symbol === symbol);
      if (!tile) {
        tile = document.createElement("article"); tile.className = "market-index"; tile.dataset.symbol = symbol;
        const name = document.createElement("span"); name.className = "index-symbol"; name.textContent = symbol;
        const price = document.createElement("strong"), change = document.createElement("span"); change.className = "index-change";
        tile.append(name, price, change); host.append(tile);
      }
      const quote = bySymbol.get(symbol), price = tile.querySelector("strong"), change = tile.querySelector(".index-change");
      price.textContent = quote ? fmt(quote.last_price) : "—";
      change.textContent = quote ? `${Number(quote.change_percent) >= 0 ? "+" : ""}${Number(quote.change_percent).toFixed(2)}%` : "Awaiting Kite quote";
      change.className = quote ? `index-change ${Number(quote.change_percent) >= 0 ? "positive" : "negative"}` : "index-change subtle";
      tile.title = quote ? `Observed ${new Date(quote.observed_at).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" })} IST · ${quote.freshness.toLowerCase()}` : "No stored quote";
    }
    status.textContent = quotes.some(q => q.freshness === "FRESH") ? "Live Kite quotes" : quotes.length ? "Last available quotes" : "Waiting for market login";
  }
  async function load() {
    if (loading || document.hidden) return;
    loading = true;
    try { render((await Screener.api("/api/market/indices/quotes")).quotes); }
    catch { status.textContent = "Quotes unavailable"; }
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
  document.getElementById("index-prev").onclick = () => host.scrollBy({ left: -360, behavior: "smooth" });
  document.getElementById("index-next").onclick = () => host.scrollBy({ left: 360, behavior: "smooth" });
  host.tabIndex = 0; host.onmouseenter = host.onfocusin = () => paused = true; host.onmouseleave = host.onfocusout = () => paused = false;
  render([]); load();
  const quoteTimer = setInterval(load, 5000);
  const scrollTimer = setInterval(() => {
    if (paused || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    host.scrollTo({ left: host.scrollLeft + host.clientWidth >= host.scrollWidth - 2 ? 0 : host.scrollLeft + 180, behavior: "smooth" });
  }, 5000);
  window.addEventListener("pagehide", () => { clearInterval(quoteTimer); clearInterval(scrollTimer); });
})();
