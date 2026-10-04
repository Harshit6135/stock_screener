"""Read-only, allowlisted access to operator documentation for the UI."""

from pathlib import Path

from flask import Blueprint, jsonify, render_template
from markdown_it import MarkdownIt


_WIKI_DIRECTORY = Path(__file__).resolve().parents[3] / "docs" / "wiki"
_PAGES = {
    "getting-started": "Getting started",
    "research-and-strategies": "Research and strategies",
    "portfolio-and-actions": "Portfolio and actions",
    "operations": "Operations and observability",
    "api-and-data": "API and data model",
    "troubleshooting": "Troubleshooting",
    "historical-positional-trend-reference": "Historical positional-trend reference",
}
_SECTIONS = {
    "getting-started": "Start here",
    "research-and-strategies": "Research",
    "portfolio-and-actions": "Portfolio",
    "operations": "Operations",
    "api-and-data": "Reference",
    "troubleshooting": "Reference",
    "historical-positional-trend-reference": "Archive",
}
_MARKDOWN = MarkdownIt("default", {"html": False, "linkify": False, "typographer": True})


def create_wiki_blueprint() -> Blueprint:
    blueprint = Blueprint("wiki", __name__)

    @blueprint.get("/wiki")
    def wiki_page():
        return render_template("wiki.html", active_page="wiki")

    @blueprint.get("/api/wiki/pages")
    def pages():
        return jsonify(
            {
                "pages": [
                    {"slug": slug, "title": title, "section": _SECTIONS[slug]}
                    for slug, title in _PAGES.items()
                ]
            }
        )

    @blueprint.get("/api/wiki/pages/<slug>")
    def read_page(slug: str):
        title = _PAGES.get(slug)
        if title is None:
            return jsonify({"error": "wiki page not found"}), 404
        path = _WIKI_DIRECTORY / f"{slug}.md"
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            return jsonify({"error": "wiki page is unavailable"}), 503
        return jsonify(
            {
                "slug": slug,
                "title": title,
                "section": _SECTIONS[slug],
                "content": content,
                "content_html": _MARKDOWN.render(content),
            }
        )

    return blueprint
