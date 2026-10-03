"""Template routes for the browser UI.

The API blueprints own all data and commands. This module only selects
templates, preventing page behaviour from diverging from API contracts.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from flask import Blueprint, render_template


def create_dashboard_blueprint() -> Blueprint:
    blueprint = Blueprint("dashboard_v2", __name__, template_folder="../../../templates")

    def page(template_name: str, **context: object):
        return render_template(template_name, **context)

    @blueprint.get("/")
    def home():
        return page("home.html", active_page="home")

    @blueprint.get("/actions")
    def actions_page():
        return page("actions.html", active_page="actions")

    @blueprint.get("/pipeline")
    def pipeline_page():
        today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
        return page("pipeline.html", active_page="pipeline", default_start=(today - timedelta(days=7)).isoformat(), default_end=(today - timedelta(days=1)).isoformat())

    @blueprint.get("/rankings")
    def rankings_page():
        return page("rankings.html", active_page="rankings")

    @blueprint.get("/universe")
    def universe_page():
        return page("universe.html", active_page="universe")

    @blueprint.get("/backtest")
    def backtest_page():
        return page("backtest.html", active_page="backtest")

    @blueprint.get("/settings")
    def settings_page():
        return page("settings.html", active_page="settings")

    @blueprint.get("/logs")
    def logs_page():
        return page("logs.html", active_page="logs")

    return blueprint
