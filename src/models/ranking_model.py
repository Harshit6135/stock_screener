from sqlalchemy import Index, PrimaryKeyConstraint

from db import db


class RankingModel(db.Model):
    """Weekly rankings with avg composite scores, tagged by strategy."""

    __tablename__ = "ranking"

    tradingsymbol = db.Column(db.String(50), nullable=False)
    ranking_date = db.Column(db.Date, nullable=False)
    strategy_id = db.Column(db.String(20), nullable=False, default="strategy1")
    composite_score = db.Column(db.Float, nullable=False)
    rank = db.Column(db.Integer, nullable=False)  # Rank 1 = highest score

    __table_args__ = (
        PrimaryKeyConstraint("tradingsymbol", "ranking_date", "strategy_id"),
        Index("idx_ranking_date", "ranking_date"),
        Index("idx_ranking_score", "composite_score"),
        Index("idx_ranking_strategy", "strategy_id", "ranking_date"),
    )

    def __repr__(self):
        return f"<Ranking {self.tradingsymbol} [{self.strategy_id}] rank={self.rank} score={self.composite_score} @ {self.ranking_date}>"
