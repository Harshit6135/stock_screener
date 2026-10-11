(() => {
  const button = document.getElementById("sidebar-toggle");
  if (!button) return;
  const root = document.documentElement;
  const key = "screener-sidebar-collapsed";
  function apply(collapsed) {
    root.dataset.sidebarCollapsed = String(collapsed);
    button.setAttribute("aria-expanded", String(!collapsed));
    button.setAttribute("aria-label", collapsed ? "Expand sidebar" : "Collapse sidebar");
    button.title = button.getAttribute("aria-label");
    button.firstElementChild.textContent = collapsed ? "›" : "‹";
  }
  try { apply(localStorage.getItem(key) === "true"); }
  catch { apply(root.dataset.sidebarCollapsed === "true"); }
  button.addEventListener("click", () => {
    const collapsed = root.dataset.sidebarCollapsed !== "true";
    apply(collapsed);
    try { localStorage.setItem(key, String(collapsed)); } catch {}
  });
  window.addEventListener("storage", event => {
    if (event.key === key) apply(event.newValue === "true");
  });
})();
