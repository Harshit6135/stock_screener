from datetime import date, timedelta
from db import db
from sqlalchemy.exc import SQLAlchemyError

from config import setup_logger
from models import ScoreModel, RankingModel

logger = setup_logger(name="ScoreRepository")


class ScoreRepository:
    """Repository for Score and Ranking table operations"""
    
    # ========== Score Table Operations ==========
    
    @staticmethod
    def bulk_insert(score_records):
        """Bulk insert score records"""
        try:
            db.session.bulk_insert_mappings(ScoreModel, score_records, return_defaults=True)
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            logger.error(f"Error inserting score records: {e}")
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
            logger.error(f"Error deleting score records: {e}")
            return None
        return True
    
    @staticmethod
    def get_max_score_date():
        """Get the latest score_date from score table"""
        latest = ScoreModel.query.order_by(ScoreModel.score_date.desc()).first()
        return latest.score_date if latest else None

    @staticmethod
    def delete_after_date(date):
        """Delete all score records after a given date."""
        try:
            num_deleted = ScoreModel.query.filter(
                ScoreModel.score_date > date
            ).delete()
            db.session.commit()
            return num_deleted
        except SQLAlchemyError as e:
            db.session.rollback()
            return -1
    
    # ========== Ranking Table Operations (was AvgScore) ==========
    
    @staticmethod
    def bulk_insert_ranking(ranking_records):
        """Bulk insert ranking records (was bulk_insert_avg)"""
        try:
            db.session.bulk_insert_mappings(RankingModel, ranking_records, return_defaults=True)
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            logger.error(f"Error inserting ranking records: {e}")
            return None
        return ranking_records
    
    @staticmethod
    def delete_all_ranking():
        """Delete all records from ranking table (for recalculation)"""
        try:
            db.session.query(RankingModel).delete()
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            logger.error(f"Error deleting ranking records: {e}")
            return None
        return True
    
    @staticmethod
    def get_max_ranking_date():
        """Get the latest ranking_date from ranking table"""
        latest = RankingModel.query.order_by(RankingModel.ranking_date.desc()).first()
        return latest.ranking_date if latest else None
    
    @staticmethod
    def get_top_n_by_date(n, ranking_date=None):
        """Get top N stocks by composite_score for a given date"""
        if ranking_date is None:
            ranking_date = db.session.query(db.func.max(RankingModel.ranking_date)).scalar()
            if not ranking_date:
                return []
        
        return RankingModel.query.filter(
            RankingModel.ranking_date == ranking_date
        ).order_by(
            RankingModel.rank.asc()  # Rank 1 = highest
        ).limit(n).all()
    
    @staticmethod
    def get_by_symbol(symbol, ranking_date=None):
        """Get latest ranking for a symbol"""
        if ranking_date:
            return RankingModel.query.filter(
                RankingModel.tradingsymbol == symbol,
                RankingModel.ranking_date == ranking_date
            ).first()
        return RankingModel.query.filter(
            RankingModel.tradingsymbol == symbol
        ).order_by(RankingModel.ranking_date.desc()).first()

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
        ).order_by(RankingModel.rank.asc()).all()
    
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

    @staticmethod
    def delete_ranking_after_date(date):
        """Delete all ranking records after a given date."""
        try:
            num_deleted = RankingModel.query.filter(
                RankingModel.ranking_date > date
            ).delete()
            db.session.commit()
            return num_deleted
        except SQLAlchemyError as e:
            db.session.rollback()
            return -1
