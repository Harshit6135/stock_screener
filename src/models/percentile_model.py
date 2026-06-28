from sqlalchemy import Index, PrimaryKeyConstraint

from db import db


class PercentileModel(db.Model):
    """Daily percentile ranks for each stock, tagged by strategy."""

    __tablename__ = "percentile"

    tradingsymbol = db.Column(db.String(50), nullable=False)
    percentile_date = db.Column(db.Date, nullable=False)
    strategy_id = db.Column(db.String(20), nullable=False, default="strategy1")
    close = db.Column(db.Float, nullable=True)
    factor_trend = db.Column(db.Float, nullable=True)
    trend_percentile = db.Column(db.Float, nullable=True)
    factor_momentum = db.Column(db.Float, nullable=True)
    momentum_percentile = db.Column(db.Float, nullable=True)
    factor_efficiency = db.Column(db.Float, nullable=True)
    efficiency_percentile = db.Column(db.Float, nullable=True)
    factor_volume = db.Column(db.Float, nullable=True)
    volume_percentile = db.Column(db.Float, nullable=True)
    factor_structure = db.Column(db.Float, nullable=True)
    structure_percentile = db.Column(db.Float, nullable=True)

    __table_args__ = (
        PrimaryKeyConstraint("tradingsymbol", "percentile_date", "strategy_id"),
        Index("idx_percentile_date", "percentile_date"),
        Index("idx_percentile_strategy", "strategy_id", "percentile_date"),
    )
