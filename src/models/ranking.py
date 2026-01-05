from db import db
from sqlalchemy import PrimaryKeyConstraint, Index


class RankingModel(db.Model):
    """Weekly rankings with avg composite scores (renamed from AvgScoreModel)"""
    __tablename__ = "ranking"

    tradingsymbol = db.Column(db.String(50), nullable=False)
    ranking_date = db.Column(db.Date, nullable=False)
    composite_score = db.Column(db.Float, nullable=False)
    rank = db.Column(db.Integer, nullable=False)  # Rank 1 = highest score

    __table_args__ = (
        PrimaryKeyConstraint("tradingsymbol", "ranking_date"),
        Index("idx_ranking_date", "ranking_date"),
        Index("idx_ranking_score", "composite_score"),
    )

    def __repr__(self):
        return f"<Ranking {self.tradingsymbol} rank={self.rank} score={self.composite_score} @ {self.ranking_date}>"
