from db import db
from sqlalchemy import PrimaryKeyConstraint, Index


class IndicatorsModel(db.Model):
    __tablename__ = "indicators"

    instrument_token = db.Column(db.Integer, nullable=False)
    date = db.Column(db.Date, nullable=False)

    tradingsymbol = db.Column(db.String, nullable=False)
    exchange = db.Column(db.String, nullable=False)

    ema_50 = db.Column(db.Float, nullable=True) 
    ema_200 = db.Column(db.Float, nullable=True)
    rsi_14 = db.Column(db.Float, nullable=True)
    roc_10 = db.Column(db.Float, nullable=True)
    roc_20 = db.Column(db.Float, nullable=True)
    sma_20 = db.Column(db.Float, nullable=True)
    stochk_14_3_3 = db.Column(db.Float, nullable=True)
    stochd_14_3_3 = db.Column(db.Float, nullable=True)
    stochh_14_3_3 = db.Column(db.Float, nullable=True)
    ppo_12_26_9 = db.Column(db.Float, nullable=True)
    ppoh_12_26_9 = db.Column(db.Float, nullable=True)
    ppos_12_26_9 = db.Column(db.Float, nullable=True)
    macd_12_26_9 = db.Column(db.Float, nullable=True)
    macdh_12_26_9 = db.Column(db.Float, nullable=True)
    macds_12_26_9 = db.Column(db.Float, nullable=True)
    bbl_20_2_2 = db.Column(db.Float, nullable=True)
    bbm_20_2_2 = db.Column(db.Float, nullable=True)
    bbu_20_2_2 = db.Column(db.Float, nullable=True)
    bbb_20_2_2 = db.Column(db.Float, nullable=True)
    bbp_20_2_2 = db.Column(db.Float, nullable=True)
    atrr_14 = db.Column(db.Float, nullable=True)
    rsi_signal_ema_3 = db.Column(db.Float, nullable=True)
    vol_sma_20 = db.Column(db.Float, nullable=True)
    price_vol_correlation = db.Column(db.Float, nullable=True)
    percent_b = db.Column(db.Float, nullable=True)
    ema_50_slope = db.Column(db.Float, nullable=True)
    distance_from_ema_200 = db.Column(db.Float, nullable=True)
    distance_from_ema_50 = db.Column(db.Float, nullable=True)
    risk_adjusted_return = db.Column(db.Float, nullable=True)
    rvol = db.Column(db.Float, nullable=True)
    roc_60 = db.Column(db.Float, nullable=True)  # 3-month momentum
    roc_125 = db.Column(db.Float, nullable=True)  # 6-month momentum
    atr_spike = db.Column(db.Float, nullable=True)  # ATR / ATR_20_avg

    __table_args__ = (
        # composite primary key
        PrimaryKeyConstraint("instrument_token", "date"),

        # fast lookup by ticker + date
        Index("idx_indicator_tradingsymbol_date", "tradingsymbol", "date"),
    )

    def __repr__(self):
        return f"<Indicator {self.tradingsymbol} {self.date}>"
