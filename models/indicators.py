from sqlalchemy import ForeignKey, PrimaryKeyConstraint, Index
from db import db

class IndicatorsModel(db.Model):
    __tablename__ = "indicators"

    instrument_token = db.Column(
        db.Integer,
        nullable=False
    )
    date = db.Column(db.Date, nullable=False)

    # denormalized for fast access
    tradingsymbol = db.Column(db.String, nullable=False)
    exchange = db.Column(db.String, nullable=False)

    rsi_14 = db.Column(db.Float)
    ema_50 = db.Column(db.Float)
    ema_200 = db.Column(db.Float)
    macd = db.Column(db.Float)

    ema_50 = db.Column(db.Float)
    ema_200 = db.Column(db.Float)
    rsi_14_3 = db.Column(db.Float)
    rsi_14_3_signal = db.Column(db.Float)
    roc_10 = db.Column(db.Float)
    stoch_14_3_k = db.Column(db.Float)
    stoch_14_3_d = db.Column(db.Float)
    bbands_20_2_125_lower = db.Column(db.Float)
    bbands_20_2_125_upper = db.Column(db.Float)
    bbands_20_2_125_sma = db.Column(db.Float)
    bbands_20_2_125_bbw = db.Column(db.Float)
    bbands_20_2_125_hist_low = db.Column(db.Float)
    macd_12_26_9 = db.Column(db.Float)
    macd_12_26_9_signal = db.Column(db.Float)
    volume_5 = db.Column(db.Float)
    volume_20 = db.Column(db.Float)

    __table_args__ = (
        # composite primary key
        PrimaryKeyConstraint("instrument_token", "date"),

        # fast lookup by ticker + date
        Index("idx_indicator_tradingsymbol_date", "tradingsymbol", "date"),
    )

    def __repr__(self):
        return f"<Indicator {self.tradingsymbol} {self.date}>"
