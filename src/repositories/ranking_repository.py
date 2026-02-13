from db import db
from sqlalchemy.exc import SQLAlchemyError

from config import setup_logger
from models import RankingModel

logger = setup_logger(name="RankingRepository")


class RankingRepository:
    """
    Repository for all ranking table operations.
    Consolidates ranking methods previously split across ScoreRepository.
    """
    
    @staticmethod
    def bulk_insert(ranking_records):
        """Bulk insert ranking records"""
        try:
            db.session.bulk_insert_mappings(RankingModel, ranking_records, return_defaults=True)
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            logger.error(f"Error inserting ranking records: {e}")
            return None
        return ranking_records

    @staticmethod
    def delete(ranking_date):
        """Delete rankings for a specific date"""
        try:
            db.session.query(RankingModel).filter(RankingModel.ranking_date == ranking_date).delete()
            db.session.commit()
        except SQLAlchemyError as e:
            logger.error(f"Error deleting rankings for date {ranking_date}: {e}")
            db.session.rollback()
            return None
        return True

    @staticmethod
    def delete_all():
        """Delete all records from ranking table (for recalculation)"""
        try:
            db.session.query(RankingModel).delete()
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            logger.error(f"Error deleting all ranking records: {e}")
            return None
        return True

    @staticmethod
    def delete_after_date(date):
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

    @staticmethod
    def get_max_ranking_date():
        """Get the latest ranking_date from ranking table"""
        latest_record = RankingModel.query.order_by(RankingModel.ranking_date.desc()).first()
        return latest_record.ranking_date if latest_record else None

    @staticmethod
    def get_top_n_by_date(n, date=None):
        """Get top N stocks by rank for a given date (rank 1 = highest)"""
        if date is None:
            latest = db.session.query(db.func.max(RankingModel.ranking_date)).scalar()
            if not latest:
                return []
        else:
            latest = date
        rankings = RankingModel.query.filter(
            RankingModel.ranking_date == latest
        ).order_by(
            RankingModel.rank.asc()
        ).limit(n).all()

        return rankings

    @staticmethod
    def get_rankings_by_date(ranking_date):
        """Get rankings for a specific date, ordered by rank"""
        return RankingModel.query.filter(
            RankingModel.ranking_date == ranking_date
        ).order_by(RankingModel.rank.asc()).all()

    @staticmethod
    def get_by_symbol(symbol, ranking_date=None):
        """Get latest ranking for a symbol, optionally for a specific date"""
        if ranking_date:
            return RankingModel.query.filter(
                RankingModel.tradingsymbol == symbol,
                RankingModel.ranking_date == ranking_date
            ).first()
        return RankingModel.query.filter(
            RankingModel.tradingsymbol == symbol
        ).order_by(RankingModel.ranking_date.desc()).first()

    @staticmethod
    def get_latest_rank_by_symbol(symbol):
        """Get the latest available ranking record for a symbol"""
        return RankingModel.query.filter(
            RankingModel.tradingsymbol == symbol
        ).order_by(RankingModel.ranking_date.desc()).first()

    @staticmethod
    def get_rankings_by_date_and_symbol(ranking_date, symbol):
        """Get ranking for a specific date and symbol"""
        return RankingModel.query.filter(
            RankingModel.ranking_date == ranking_date,
            RankingModel.tradingsymbol == symbol
        ).order_by(RankingModel.composite_score.desc()).first()

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
    def get_distinct_ranking_dates():
        """Get all distinct ranking dates"""
        result = db.session.query(RankingModel.ranking_date).distinct().order_by(RankingModel.ranking_date).all()
        return [r[0] for r in result]
