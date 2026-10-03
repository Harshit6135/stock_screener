"""Read-only, allowlisted access to operator documentation for the UI."""

from pathlib import Path

from flask import Blueprint, jsonify, render_template


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


def create_wiki_blueprint() -> Blueprint:
    blueprint = Blueprint("wiki_v2", __name__)

    @blueprint.get("/wiki")
    def wiki_page():
        return render_template("wiki.html", active_page="wiki")

    @blueprint.get("/api/v2/wiki/pages")
    def pages():
        return jsonify({"pages": [{"slug": slug, "title": title} for slug, title in _PAGES.items()]})

    @blueprint.get("/api/v2/wiki/pages/<slug>")
    def read_page(slug: str):
        title = _PAGES.get(slug)
        if title is None:
            return jsonify({"error": "wiki page not found"}), 404
        path = _WIKI_DIRECTORY / f"{slug}.md"
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            return jsonify({"error": "wiki page is unavailable"}), 503
        return jsonify({"slug": slug, "title": title, "content": content})

    return blueprint
