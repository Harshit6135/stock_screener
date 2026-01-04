from db import db
from flask_smorest import Api
from flask_migrate import Migrate
from flask import Flask, render_template

from config import Config
from src.api.v1.routes import (
    actions_bp,
    instruments_bp,
    marketdata_bp,
    indicators_bp,
    portfolio_bp,
    ranking_bp,
    init_bp,
    score_bp
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

# Register API blueprints
api.register_blueprint(init_bp)
api.register_blueprint(instruments_bp)
api.register_blueprint(marketdata_bp)
api.register_blueprint(indicators_bp)
api.register_blueprint(actions_bp)
api.register_blueprint(ranking_bp)
api.register_blueprint(portfolio_bp)
api.register_blueprint(score_bp)


# Main Dashboard Route
@app.route("/")
def dashboard():
    """Render the main dashboard"""
    return render_template('dashboard.html')

@app.route("/strategy_cap")
def strategy_cap():
    from repositories import ConfigRepository
    config = ConfigRepository()
    data = {
        'strategy_name' : 'momentum_strategy_one',
        'initial_capital' : 100000,
        'risk_threshold' : 1,
        'max_positions' : 10,
        'buffer_percent' : 25,
        'exit_threshold' : 40,
        'sl_multiplier' : 2
    }
    config.post_config(data)

    return 'successful'

@app.route("/strategy")
def run_strategy():
    from strategies.main import strategy_backtesting
    strategy_backtesting('strategy_one')

    return 'successful'

if __name__ == "__main__":
    app.run(debug=True)