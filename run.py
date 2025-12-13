from flask import Flask
from flask_smorest import Api
from flask_migrate import Migrate
from config import Config
from db import db

from resources import InstrumentsBlueprint, MarketDataBlueprint


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

app.route("/home")
def home():
    


if __name__ == "__main__":
    app.run(debug=True)
