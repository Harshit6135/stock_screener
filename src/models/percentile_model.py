from db import db
from sqlalchemy import PrimaryKeyConstraint, Index


class PercentileModel(db.Model):
    """Daily percentile ranks for each stock"""
    __tablename__ = "percentile"

    tradingsymbol = db.Column(db.String(50), nullable=False)
    percentile_date = db.Column(db.Date, nullable=False)
    
    ema_50_slope = db.Column(db.Float, nullable=True)
    trend_rank = db.Column(db.Float, nullable=True)
    distance_from_ema_200 = db.Column(db.Float, nullable=True)
    trend_extension_rank = db.Column(db.Float, nullable=True)
    distance_from_ema_50 = db.Column(db.Float, nullable=True)
    trend_start_rank = db.Column(db.Float, nullable=True)
    rsi_signal_ema_3 = db.Column(db.Float, nullable=True)
    momentum_rsi_rank = db.Column(db.Float, nullable=True)
    ppo_12_26_9 = db.Column(db.Float, nullable=True)
    momentum_ppo_rank = db.Column(db.Float, nullable=True)
    ppoh_12_26_9 = db.Column(db.Float, nullable=True)
    momentum_ppoh_rank = db.Column(db.Float, nullable=True)
    risk_adjusted_return = db.Column(db.Float, nullable=True)
    efficiency_rank = db.Column(db.Float, nullable=True)
    rvol = db.Column(db.Float, nullable=True)
    rvolume_rank = db.Column(db.Float, nullable=True)
    price_vol_correlation = db.Column(db.Float, nullable=True)
    price_vol_corr_rank = db.Column(db.Float, nullable=True)
    bbb_20_2 = db.Column(db.Float, nullable=True)
    structure_rank = db.Column(db.Float, nullable=True)
    percent_b = db.Column(db.Float, nullable=True)
    structure_bb_rank = db.Column(db.Float, nullable=True)

    __table_args__ = (
        PrimaryKeyConstraint("tradingsymbol", "percentile_date"),
        Index("idx_percentile_date", "percentile_date"),
    )
