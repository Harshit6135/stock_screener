(() => {
  const list = document.getElementById("wiki-pages");
  const title = document.getElementById("wiki-title");
  const content = document.getElementById("wiki-content");
  async function show(slug) {
    try {
      const page = await Screener.api(`/api/wiki/pages/${encodeURIComponent(slug)}`);
      title.textContent = page.title;
      content.textContent = page.content;
      history.replaceState(null, "", `#${slug}`);
    } catch (error) { content.textContent = error.message; }
  }
  document.addEventListener("DOMContentLoaded", async () => {
    try {
      const result = await Screener.api("/api/wiki/pages");
      list.replaceChildren(...result.pages.map(page => {
        const button = document.createElement("button");
        button.className = "secondary"; button.textContent = page.title;
        button.addEventListener("click", () => show(page.slug));
        return button;
      }));
      await show(location.hash.slice(1) || result.pages[0].slug);
    } catch (error) { content.textContent = error.message; }
  });
})();
