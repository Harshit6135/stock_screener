(() => {
  const link = document.getElementById("market-login");
  let checking = false, previousStatus = null;
  async function check() {
    if (checking || document.hidden) return;
    checking = true;
    try {
      const state = await Screener.api("/api/integrations/kite/market-data/status");
      link.textContent = state.status === "ACTIVE" ? "Market data connected · Refresh ↗" : state.configured ? "Log in to market data ↗" : "Configure market data ↗";
      link.href = state.configured ? "/integrations/kite?auto=1" : "/integrations/kite";
      if (state.login_required && !state.login_in_progress && previousStatus !== state.status && !sessionStorage.getItem("market-login-opened")) {
        sessionStorage.setItem("market-login-opened", "1");
        const tab = window.open(link.href, "kite-market-login");
        if (tab) tab.opener = null;
        else link.textContent = "Market login required · Open Kite ↗";
      }
      if (state.status === "ACTIVE") sessionStorage.removeItem("market-login-opened");
      if (state.status !== previousStatus) window.dispatchEvent(new CustomEvent("market-session", { detail: state }));
      previousStatus = state.status;
      window.marketSessionStatus = state;
    } catch { link.textContent = "Market connection unavailable · Retry ↗"; }
    finally { checking = false; }
  }
  window.addEventListener("focus", check);
  const timer = setInterval(check, 60000);
  window.addEventListener("pagehide", () => clearInterval(timer));
  check();
})();
