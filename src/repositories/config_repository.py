from db import db
from models import ConfigModel


class ConfigRepository:

    @staticmethod
    def get_config(config_name):
        return ConfigModel.query.filter(ConfigModel.config_name == config_name).first()

    @staticmethod
    def post_config(config_data):
        config = ConfigModel(**config_data)
        db.session.add(config)
        db.session.commit()

    @staticmethod
    def update_config(config_data):
        config = ConfigModel.query.first()
        if config:
            for key, value in config_data.items():
                setattr(config, key, value)
            db.session.commit()
