from db import db
from sqlalchemy import PrimaryKeyConstraint, Index


class ScoreModel(db.Model):
    """Daily composite scores for each stock"""
    __tablename__ = "score"

    tradingsymbol = db.Column(db.String(50), nullable=False)
    score_date = db.Column(db.Date, nullable=False)
    
    # Factor scores from FactorsService
    factor_trend = db.Column(db.Float, nullable=True)
    factor_momentum = db.Column(db.Float, nullable=True)
    factor_efficiency = db.Column(db.Float, nullable=True)
    factor_volume = db.Column(db.Float, nullable=True)
    factor_structure = db.Column(db.Float, nullable=True)
    
    # Cross-sectional percentile ranks (0-100)
    trend_rank = db.Column(db.Float, nullable=True)
    momentum_rank = db.Column(db.Float, nullable=True)
    efficiency_rank = db.Column(db.Float, nullable=True)
    volume_rank = db.Column(db.Float, nullable=True)
    structure_rank = db.Column(db.Float, nullable=True)
    
    # Final weighted composite
    composite_score = db.Column(db.Float, nullable=False)

    __table_args__ = (
        PrimaryKeyConstraint("tradingsymbol", "score_date"),
        Index("idx_score_date", "score_date"),
    )

    def __repr__(self):
        return f"<Score {self.tradingsymbol} score={self.composite_score} @ {self.score_date}>"
