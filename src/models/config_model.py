from db import db


class ConfigModel(db.Model):
    """Portfolio-level risk configuration parameters"""
    __tablename__ = "config"
    __bind_key__ = "personal"

    id = db.Column(db.Integer, primary_key=True, autoincrement = True)
    config_name = db.Column(db.String, nullable=False)
    initial_capital = db.Column(db.Float, nullable=False, default=100000.0)
    risk_threshold = db.Column(db.Float, nullable=False, default=1.0)
    max_positions = db.Column(db.Integer, nullable=False, default=15)
    buffer_percent = db.Column(db.Float, nullable=False, default=0.25)
    exit_threshold = db.Column(db.Float, nullable=False, default=40.0)
    sl_multiplier = db.Column(db.Float, nullable=False, default=2.0)
    sl_step_percent = db.Column(db.Float, nullable=False, default=0.10)
    sl_fallback_percent = db.Column(db.Float, nullable=False, default=0.06)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, onupdate=db.func.now())

    def __repr__(self):
        return f"<Config Name={self.config_name}>"
