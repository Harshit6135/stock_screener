"""
Stock Screener V3 - Flask Application

Multi-factor momentum screening and portfolio management system.
"""
from db import db
from flask import Flask
from flask_smorest import Api
from flask_migrate import Migrate
from config.flask_config import Config

from router.main_router import main_bp
from resources import InstrumentsBlueprint, MarketDataBlueprint, IndicatorsBlueprint, PortfolioBlueprint


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

# Register blueprints
app.register_blueprint(main_bp)
api.register_blueprint(InstrumentsBlueprint)
api.register_blueprint(MarketDataBlueprint)
api.register_blueprint(IndicatorsBlueprint)
api.register_blueprint(PortfolioBlueprint)


if __name__ == "__main__":
    app.run(debug=True)