from db import db
from sqlalchemy import PrimaryKeyConstraint, Index


class ScoreModel(db.Model):
    """Daily composite scores for each stock"""
    __tablename__ = "score"

    tradingsymbol = db.Column(db.String(50), nullable=False)
    score_date = db.Column(db.Date, nullable=False)
    initial_composite_score = db.Column(db.Float, nullable=False)
    penalty = db.Column(db.Float, nullable=True)
    penalty_reason = db.Column(db.String(255), nullable=True)
    composite_score = db.Column(db.Float, nullable=False)
    

    __table_args__ = (
        PrimaryKeyConstraint("tradingsymbol", "score_date"),
        Index("idx_score_date", "score_date"),
    )

    def __repr__(self):
        return f"<Score {self.tradingsymbol} score={self.composite_score} @ {self.score_date}>"