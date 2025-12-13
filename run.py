from flask import Flask
from flask_smorest import Api
# from flask_migrate import Migrate
from config.flask_config import Config
from db import db

from resources import InstrumentsBlueprint, MarketDataBlueprint, StrategyBlueprint, IndicatorsBlueprint
from router.main_router import orchestrator

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    return app

app = create_app()
db.init_app(app)
# migrate = Migrate(app, db)
api = Api(app)

# Create all database tables
with app.app_context():
    db.create_all()

api.register_blueprint(InstrumentsBlueprint)
api.register_blueprint(MarketDataBlueprint)
api.register_blueprint(StrategyBlueprint)
api.register_blueprint(IndicatorsBlueprint)

@app.route("/home")
def home():
    orchestrator()
    return "Orchestrator completed."


if __name__ == "__main__":
    app.run(debug=True)
