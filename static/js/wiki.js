(() => {
  const $ = id => document.getElementById(id);
  let pages = [];
  let activeSlug = "";
  let requestSequence = 0;

  function renderNavigation(filter = "") {
    const navigation = $("wiki-pages");
    if (!navigation) return;
    const query = filter.trim().toLocaleLowerCase();
    const visible = pages.filter(page => `${page.title} ${page.section}`.toLocaleLowerCase().includes(query));
    const sections = [...new Set(visible.map(page => page.section))];
    navigation.replaceChildren(...sections.map(sectionName => {
      const section = document.createElement("section"); section.className = "wiki-page-group";
      const heading = document.createElement("h2"); heading.textContent = sectionName; section.append(heading);
      visible.filter(page => page.section === sectionName).forEach(page => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = `wiki-page-link${page.slug === activeSlug ? " active" : ""}`;
        if (page.slug === activeSlug) button.setAttribute("aria-current", "page");
        button.textContent = page.title;
        button.onclick = () => show(page.slug);
        section.append(button);
      });
      return section;
    }));
    if ($("wiki-page-count")) $("wiki-page-count").textContent = `${visible.length} of ${pages.length} guides`;
  }

  function renderContents() {
    const content = $("wiki-content"), toc = $("wiki-toc"), nav = $("wiki-toc-links");
    if (!content || !toc || !nav) return;
    content.querySelectorAll("table").forEach(table => {
      if (table.parentElement?.classList.contains("wiki-table-scroll")) return;
      const wrapper = document.createElement("div");
      wrapper.className = "wiki-table-scroll";
      table.before(wrapper); wrapper.append(table);
    });
    const headings = [...content.querySelectorAll("h2, h3")];
    nav.replaceChildren(...headings.map(heading => {
      const base = heading.textContent.toLocaleLowerCase().normalize("NFKD")
        .replace(/[^\w\s-]/g, "").trim().replace(/[\s-]+/g, "-") || "section";
      let id = base, suffix = 2;
      while ([...content.querySelectorAll("[id]")].some(item => item !== heading && item.id === id)) id = `${base}-${suffix++}`;
      heading.id = id;
      const link = document.createElement("a");
      link.href = `#${id}`; link.textContent = heading.textContent;
      if (heading.tagName === "H3") link.className = "wiki-toc-subsection";
      return link;
    }));
    toc.hidden = headings.length < 3; toc.open = headings.length >= 3;
  }

  async function show(slug) {
    const index = pages.findIndex(page => page.slug === slug);
    if (index < 0) return;
    const request = ++requestSequence, page = pages[index], content = $("wiki-content");
    if (!content) return;
    activeSlug = slug;
    renderNavigation($("wiki-search")?.value || "");
    if ($("wiki-title")) $("wiki-title").textContent = page.title;
    if ($("wiki-category")) $("wiki-category").textContent = page.section || "Guide";
    content.textContent = "Loading guide…"; content.classList.remove("error");
    if ($("wiki-reading-time")) $("wiki-reading-time").textContent = "";
    try {
      const response = await Screener.api(`/api/wiki/pages/${encodeURIComponent(slug)}`);
      if (request !== requestSequence) return;
      if (typeof response.content_html !== "string" || !response.content_html.trim())
        throw new Error("The guide response did not include rendered Markdown.");
      content.innerHTML = response.content_html;
      renderContents();
      const words = (response.content || "").trim().split(/\s+/).filter(Boolean).length;
      if ($("wiki-reading-time")) $("wiki-reading-time").textContent = `${Math.max(1, Math.ceil(words / 220))} min read`;
      history.replaceState(null, "", `#${slug}`);
    } catch (error) {
      if (request !== requestSequence) return;
      content.textContent = error.message || "Unable to load this guide.";
      content.classList.add("error");
    }
    if ($("wiki-position")) $("wiki-position").textContent = `Guide ${index + 1} of ${pages.length}`;
    if ($("wiki-previous")) $("wiki-previous").disabled = index === 0;
    if ($("wiki-next")) $("wiki-next").disabled = index === pages.length - 1;
  }

  document.addEventListener("DOMContentLoaded", async () => {
    try {
      const result = await Screener.api("/api/wiki/pages");
      pages = result.pages || [];
      if (!pages.length) {
        if ($("wiki-content")) $("wiki-content").textContent = "No guide pages are available.";
        return;
      }
      renderNavigation();
      if ($("wiki-total-count")) $("wiki-total-count").textContent = `${pages.length} ARTICLES`;
      $("wiki-search")?.addEventListener("input", event => renderNavigation(event.target.value));
      if ($("wiki-previous")) $("wiki-previous").onclick = () => {
        const index = pages.findIndex(page => page.slug === activeSlug);
        if (index > 0) show(pages[index - 1].slug);
      };
      if ($("wiki-next")) $("wiki-next").onclick = () => {
        const index = pages.findIndex(page => page.slug === activeSlug);
        if (index >= 0 && index < pages.length - 1) show(pages[index + 1].slug);
      };
      const requested = location.hash.slice(1);
      await show(pages.some(page => page.slug === requested) ? requested : pages[0].slug);
    } catch (error) {
      const content = $("wiki-content");
      if (content) { content.textContent = error.message || "Unable to load the guide index."; content.classList.add("error"); }
    }
  });
})();
