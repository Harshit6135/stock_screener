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
    init_bp
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


# Main Dashboard Route
@app.route("/")
def dashboard():
    """Render the main dashboard"""
    return render_template('dashboard.html')

if __name__ == "__main__":
    app.run(debug=True)