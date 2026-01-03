from datetime import date, timedelta
from db import db
from sqlalchemy.exc import SQLAlchemyError

from models import ScoreModel, AvgScoreModel, RankingModel


class ScoreRepository:
    """Repository for Score and AvgScore table operations"""
    
    # ========== Score Table Operations ==========
    
    @staticmethod
    def bulk_insert(score_records):
        """Bulk insert score records"""
        try:
            db.session.bulk_insert_mappings(ScoreModel, score_records, return_defaults=True)
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            print(f"Error inserting score records: {e}")
            return None
        return score_records
    
    @staticmethod
    def delete_all():
        """Delete all records from score table (for recalculation)"""
        try:
            db.session.query(ScoreModel).delete()
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            print(f"Error deleting score records: {e}")
            return None
        return True
    
    @staticmethod
    def get_max_score_date():
        """Get the latest score_date from score table"""
        latest = ScoreModel.query.order_by(ScoreModel.score_date.desc()).first()
        return latest.score_date if latest else None
    
    # ========== Avg Score Table Operations ==========
    
    @staticmethod
    def bulk_insert_avg(avg_records):
        """Bulk insert avg_score records"""
        try:
            db.session.bulk_insert_mappings(AvgScoreModel, avg_records, return_defaults=True)
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            print(f"Error inserting avg_score records: {e}")
            return None
        return avg_records
    
    @staticmethod
    def delete_all_avg():
        """Delete all records from avg_score table (for recalculation)"""
        try:
            db.session.query(AvgScoreModel).delete()
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            print(f"Error deleting avg_score records: {e}")
            return None
        return True
    
    @staticmethod
    def get_max_avg_score_date():
        """Get the latest score_date (Monday) from avg_score table"""
        latest = AvgScoreModel.query.order_by(AvgScoreModel.score_date.desc()).first()
        return latest.score_date if latest else None
    
    @staticmethod
    def get_top_n_by_date(n, score_date=None):
        """Get top N stocks by avg composite_score for a given date"""
        if score_date is None:
            score_date = db.session.query(db.func.max(AvgScoreModel.score_date)).scalar()
            if not score_date:
                return []
        
        return AvgScoreModel.query.filter(
            AvgScoreModel.score_date == score_date
        ).order_by(
            AvgScoreModel.composite_score.desc()
        ).limit(n).all()
    
    @staticmethod
    def get_by_symbol(symbol, score_date=None):
        """Get latest avg score for a symbol"""
        if score_date:
            return AvgScoreModel.query.filter(
                AvgScoreModel.tradingsymbol == symbol,
                AvgScoreModel.score_date == score_date
            ).first()
        return AvgScoreModel.query.filter(
            AvgScoreModel.tradingsymbol == symbol
        ).order_by(AvgScoreModel.score_date.desc()).first()

    # ========== Ranking Data Fetching ==========

    @staticmethod
    def get_rankings_after_date(after_date):
        """Get all ranking records after a given date"""
        return RankingModel.query.filter(
            RankingModel.ranking_date > after_date
        ).order_by(RankingModel.ranking_date).all()
    
    @staticmethod
    def get_all_rankings():
        """Get all ranking records"""
        return RankingModel.query.order_by(RankingModel.ranking_date).all()
    
    @staticmethod
    def get_rankings_by_date(ranking_date):
        """Get rankings for a specific date"""
        return RankingModel.query.filter(
            RankingModel.ranking_date == ranking_date
        ).all()
    
    @staticmethod
    def get_distinct_ranking_dates():
        """Get all distinct ranking dates"""
        result = db.session.query(RankingModel.ranking_date).distinct().order_by(RankingModel.ranking_date).all()
        return [r[0] for r in result]

    @staticmethod
    def get_scores_in_date_range(start_date, end_date):
        """Get all score records within a date range"""
        return ScoreModel.query.filter(
            ScoreModel.score_date >= start_date,
            ScoreModel.score_date <= end_date
        ).all()
