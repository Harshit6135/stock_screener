from pathlib import Path

from flask import Flask

from src.gates.http.wiki import create_wiki_blueprint


def test_wiki_page_and_allowlisted_markdown_readback():
    app = Flask(__name__, template_folder=str(Path(__file__).resolve().parents[3] / "templates"))
    app.register_blueprint(create_wiki_blueprint())
    client = app.test_client()
    assert client.get("/wiki").status_code == 200
    pages = client.get("/api/wiki/pages").get_json()["pages"]
    assert any(page["slug"] == "getting-started" for page in pages)
    assert (
        "Main pages"
        in client.get("/api/wiki/pages/getting-started").get_json()["content"]
    )
    assert client.get("/api/wiki/pages/../run").status_code == 404
