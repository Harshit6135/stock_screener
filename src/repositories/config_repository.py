from db import db
from models import RiskConfigModel


class ConfigRepository:

    @staticmethod
    def get_config():
        return RiskConfigModel.query.first()

    @staticmethod
    def post_config(config_data):
        config = RiskConfigModel(**config_data)
        db.session.add(config)
        db.session.commit()

    @staticmethod
    def update_config(config_data):
        query = RiskConfigModel.query.first()
        query.update(config_data)
        db.session.commit()
