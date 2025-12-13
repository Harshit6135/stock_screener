from db import db
from numba.core.typeconv.rules import default_type_manager


class MomentumStrategyModel(db.Model):
    __tablename__ = "momentum_strategy"

    # PRIMARY KEY
    ticker = db.Column(db.String, primary_key=True)
    mcap = db.Column(db.Float, default = False)
    price_check = db.Column(db.Boolean, default=False)
    squeeze_check = db.Column(db.Boolean, default=False)
    rsi_check = db.Column(db.Boolean, default=False)
    rsi_bullish = db.Column(db.Boolean, default=False)
    roc_check = db.Column(db.Boolean, default=False)
    macd_check = db.Column(db.Boolean, default=False)
    stoch_check = db.Column(db.Boolean, default=False)
    stoch_cross = db.Column(db.Boolean, default=False)
    vol_check = db.Column(db.Boolean, default=False)
    squeeze_setup = db.Column(db.Boolean, default=False)
    momentum_setup = db.Column(db.Boolean, default=False)

    setup_type = db.Column(db.String, nullable=True)
    status = db.Column(db.String, nullable=True)
    summary = db.Column(db.Text, nullable=True)

    def __repr__(self):
        return f"<Signal {self.ticker} {self.setup_type} {self.status}>"
