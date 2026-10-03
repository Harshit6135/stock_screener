from flask import Flask

from src.gates.http.wiki import create_wiki_blueprint


def test_wiki_page_and_allowlisted_markdown_readback():
    app = Flask(__name__, template_folder="../templates")
    app.register_blueprint(create_wiki_blueprint())
    client = app.test_client()
    assert client.get("/wiki").status_code == 200
    pages = client.get("/api/v2/wiki/pages").get_json()["pages"]
    assert any(page["slug"] == "getting-started" for page in pages)
    assert (
        "Application pages"
        in client.get("/api/v2/wiki/pages/getting-started").get_json()["content"]
    )
    assert client.get("/api/v2/wiki/pages/../run").status_code == 404
