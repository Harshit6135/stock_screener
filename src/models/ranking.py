from db import db
from sqlalchemy import PrimaryKeyConstraint, Index


class RankingModel(db.Model):
    """Historical ranking data with composite scores"""
    __tablename__ = "ranking"

    tradingsymbol = db.Column(db.String(50), nullable=False)
    ranking_date = db.Column(db.Date, nullable=False)
    
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
        PrimaryKeyConstraint("tradingsymbol", "ranking_date"),
        Index("idx_ranking_date", "ranking_date"),
    )

class ScoreModel(db.Model):
    """Historical ranking data with composite scores"""
    __tablename__ = "score"

    tradingsymbol = db.Column(db.String(50), nullable=False)
    score_date = db.Column(db.Date, nullable=False)
    
    final_trend_score = db.Column(db.Float, nullable=True)
    final_momentum_score = db.Column(db.Float, nullable=True)
    final_vol_score = db.Column(db.Float, nullable=True)
    final_structure_score = db.Column(db.Float, nullable=True)
    
    # Final composite
    composite_score = db.Column(db.Float, nullable=False)

    __table_args__ = (
        PrimaryKeyConstraint("tradingsymbol", "score_date"),
        Index("idx_score_date", "score_date"),
    )

    def __repr__(self):
        return f"<Ranking {self.tradingsymbol} score={self.composite_score} @ {self.score_date}>"

class AvgScoreModel(db.Model):
    """Historical ranking data with composite scores"""
    __tablename__ = "avg_score"

    tradingsymbol = db.Column(db.String(50), nullable=False)
    score_date = db.Column(db.Date, nullable=False)
    composite_score = db.Column(db.Float, nullable=False)

    __table_args__ = (
        PrimaryKeyConstraint("tradingsymbol", "score_date"),
        Index("idx_avg_score_date", "score_date"),
        Index("idx_avg_score", "composite_score"),
    )

    def __repr__(self):
        return f"<Ranking {self.tradingsymbol} score={self.composite_score} @ {self.score_date}>"
