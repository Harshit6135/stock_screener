from flask import Flask
from flask_smorest import Api
from flask_migrate import Migrate
from config.flask_config import Config
from db import db

from resources import InstrumentsBlueprint, MarketDataBlueprint, IndicatorsBlueprint
from router.kite_router import get_latest_data
from router.day0_router import init_db
from router.indicators_router import calculate_indicators
from router.ranking_router import calculate_score

def create_app(config_class=Config):
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

api.register_blueprint(InstrumentsBlueprint)
api.register_blueprint(MarketDataBlueprint)
api.register_blueprint(IndicatorsBlueprint)

@app.route("/home")
def home():
    get_latest_data()
    return "Orchestrator completed."

@app.route("/day0")
def day0():
    init_db()
    return "Day 0 completed."

@app.route("/update_indicators")
def calc_indicators():
    calculate_indicators()
    return "Calculation of Indicators completed."

@app.route("/latest_rank")
def generate_ranking():
    calculate_score()
    return "All completed."

if __name__ == "__main__":
    app.run(debug=True)
