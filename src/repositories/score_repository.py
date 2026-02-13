from datetime import date, timedelta
from db import db
from sqlalchemy.exc import SQLAlchemyError

from config import setup_logger
from models import ScoreModel

logger = setup_logger(name="ScoreRepository")


class ScoreRepository:
    """Repository for Score table operations only.
    
    Ranking table operations have been moved to RankingRepository.
    """
    
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

    @staticmethod
    def get_scores_in_date_range(start_date, end_date):
        """Get all score records within a date range"""
        return ScoreModel.query.filter(
            ScoreModel.score_date >= start_date,
            ScoreModel.score_date <= end_date
        ).all()

    @staticmethod
    def get_all_distinct_dates():
        """Get all distinct score dates, ordered ascending.

        Returns:
            List[date]: Sorted list of unique score dates.

        Example:
            >>> dates = ScoreRepository.get_all_distinct_dates()
        """
        result = db.session.query(
            ScoreModel.score_date
        ).distinct().order_by(
            ScoreModel.score_date
        ).all()
        return [r[0] for r in result]
