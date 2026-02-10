from db import db
from flask_smorest import Api
from flask_migrate import Migrate
from flask import Flask, render_template

from config import Config
from src.api.v1.routes import (
    instruments_bp,
    marketdata_bp,
    indicators_bp,
    percentile_bp,
    init_bp,
    score_bp,
    app_bp,
    ranking_bp,
    actions_bp,
    investment_bp,
    config_bp,
    costs_bp,
    tax_bp,
    backtest_bp
)


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


# Main Dashboard Route
@app.route("/")
def dashboard():
    """Render the main dashboard"""
    return render_template('dashboard.html')


@app.route("/backtest")
def backtest():
    """Render the backtest page"""
    return render_template('backtest.html')


@app.route("/actions")
def actions():
    """Render the actions page"""
    return render_template('actions.html')


if __name__ == "__main__":
    app.run(debug=True, use_reloader=True)