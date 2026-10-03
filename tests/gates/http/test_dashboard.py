from flask import Flask

from src.gates.http.dashboard import create_dashboard_blueprint


def test_dashboard_page_routes():
    from flask import Flask

    from src.gates.http.dashboard import create_dashboard_blueprint

    app = Flask(__name__)
    app.register_blueprint(create_dashboard_blueprint())
    client = app.test_client()

    for path in (
        "/",
        "/actions",
        "/pipeline",
        "/rankings",
        "/universe",
        "/backtest",
        "/settings",
        "/logs",
    ):
        response = client.get(path)
        assert response.status_code == 200
        assert "css/carbon-emerald.css" in response.get_data(as_text=True)
    for path in ("/app", "/portfolio"):
        assert client.get(path).status_code == 404


def test_dashboard_web_routes_render():
    app = Flask(__name__)
    app.register_blueprint(create_dashboard_blueprint())
    client = app.test_client()

    for path in [
        "/",
        "/actions",
        "/backtest",
        "/pipeline",
        "/rankings",
        "/universe",
        "/settings",
        "/logs",
    ]:
        res = client.get(path)
        assert res.status_code == 200, f"failed for {path}"
        html = res.get_data(as_text=True)
        assert 'class="sidebar"' in html
    for path in ["/app", "/portfolio"]:
        assert client.get(path).status_code == 404


def test_pipeline_browser_renders_progress_and_recovery_controls():
    app = Flask(__name__)
    app.register_blueprint(create_dashboard_blueprint())
    response = app.test_client().get("/pipeline")
    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert 'id="stages"' in page
    assert 'id="submit-pipeline"' in page
    assert 'src="/static/js/pipeline.js"' in page
