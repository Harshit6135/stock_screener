from db import db
from sqlalchemy import PrimaryKeyConstraint, Index


class RankingModel(db.Model):
    """Historical ranking data with composite scores"""
    __tablename__ = "ranking"

    tradingsymbol = db.Column(db.String(50), nullable=False)
    ranking_date = db.Column(db.Date, nullable=False)
    
    # Raw metrics
    ema_50_slope = db.Column(db.Float, nullable=True)
    ppo_12_26_9 = db.Column(db.Float, nullable=True)
    ppoh_12_26_9 = db.Column(db.Float, nullable=True)
    rvol = db.Column(db.Float, nullable=True)
    price_vol_correlation = db.Column(db.Float, nullable=True)
    bbb_20_2 = db.Column(db.Float, nullable=True)
    percent_b = db.Column(db.Float, nullable=True)
    distance_from_ema_200 = db.Column(db.Float, nullable=True)
    
    # Computed ranks/scores
    trend_rank = db.Column(db.Float, nullable=True)
    trend_extension_rank = db.Column(db.Float, nullable=True)
    final_trend_score = db.Column(db.Float, nullable=True)
    momentum_rsi_rank = db.Column(db.Float, nullable=True)
    momentum_ppo_rank = db.Column(db.Float, nullable=True)
    momentum_ppoh_rank = db.Column(db.Float, nullable=True)
    final_momentum_score = db.Column(db.Float, nullable=True)
    rvolume_rank = db.Column(db.Float, nullable=True)
    price_vol_corr_rank = db.Column(db.Float, nullable=True)
    vol_score = db.Column(db.Float, nullable=True)
    efficiency_rank = db.Column(db.Float, nullable=True)
    structure_bb_rank = db.Column(db.Float, nullable=True)
    structure_rank = db.Column(db.Float, nullable=True)
    final_structure_score = db.Column(db.Float, nullable=True)
    
    # Final composite
    composite_score = db.Column(db.Float, nullable=False)
    rank_position = db.Column(db.Integer, nullable=True)

    __table_args__ = (
        PrimaryKeyConstraint("tradingsymbol", "ranking_date"),
        Index("idx_ranking_date", "ranking_date"),
        Index("idx_ranking_score", "composite_score"),
    )

    def __repr__(self):
        return f"<Ranking {self.tradingsymbol} score={self.composite_score} @ {self.ranking_date}>"
