from flask import Flask, render_template
from flask_migrate import Migrate
from flask_smorest import Api
from waitress import serve

from db import db
from src.api.v1.routes import (
    actions_bp,
    app_bp,
    backtest_bp,
    config_bp,
    costs_bp,
    index_bp,
    indicators_bp,
    init_bp,
    instruments_bp,
    investment_bp,
    marketdata_bp,
    percentile_bp,
    ranking_bp,
    score_bp,
    tax_bp,
)
from src.config import Config


def create_app(config_class=Config):
    """Application factory"""
    app = Flask(__name__)
    app.config.from_object(config_class)
    return app


app = create_app()
db.init_app(app)
migrate = Migrate(app, db)
api = Api(app)

# Create all database tables
with app.app_context():
    db.create_all()

# Register API blueprints (order matches Swagger UI / Redoc tag groups)
# System & Config
api.register_blueprint(init_bp)
api.register_blueprint(app_bp)
api.register_blueprint(config_bp)
# Data Pipeline
api.register_blueprint(instruments_bp)
api.register_blueprint(marketdata_bp)
api.register_blueprint(indicators_bp)
api.register_blueprint(percentile_bp)
api.register_blueprint(score_bp)
api.register_blueprint(ranking_bp)
# Trading
api.register_blueprint(actions_bp)
api.register_blueprint(investment_bp)
# Analysis
api.register_blueprint(costs_bp)
api.register_blueprint(tax_bp)
# Backtest
api.register_blueprint(backtest_bp)
# Market Indices (live ticker)
api.register_blueprint(index_bp)


# Main Dashboard Route
@app.route("/")
def dashboard():
    """Render the main dashboard"""
    return render_template("dashboard.html")


@app.route("/backtest")
def backtest():
    """Render the backtest page"""
    return render_template("backtest.html")


@app.route("/actions")
def actions():
    """Render the actions page"""
    return render_template("actions.html")


if __name__ == "__main__":
    import logging

    from paste.translogger import TransLogger

    # Waitress's internal logs
    logging.getLogger("waitress").setLevel(logging.INFO)

    # TransLogger captures HTTP requests and prints them to console
    logged_app = TransLogger(app, setup_console_handler=False)

    print("Starting Waitress server on http://0.0.0.0:5000 ...")

    serve(
        logged_app,
        host="0.0.0.0",
        port=5000,
        threads=3,  # SSE stream + pipeline + dashboard run concurrently
        channel_timeout=600,  # keep SSE connections alive up to 10 min
    )
