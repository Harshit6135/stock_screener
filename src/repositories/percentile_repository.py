from db import db
from sqlalchemy.exc import SQLAlchemyError

from config import setup_logger
from models import PercentileModel

logger = setup_logger(name="PercentileRepository")


class PercentileRepository:
    """Repository for percentile rank operations (renamed from RankingRepository)"""
    
    @staticmethod
    def bulk_insert(percentile_records):
        try:
            db.session.bulk_insert_mappings(PercentileModel, percentile_records, return_defaults=True)
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            logger.error(f"Error inserting Items to Table {e}")
            return None
        return percentile_records

    @staticmethod
    def delete(percentile_date):
        try:
            db.session.query(PercentileModel).filter(PercentileModel.percentile_date == percentile_date).delete()
            db.session.commit()
        except SQLAlchemyError as e:
            logger.error(f"Error deleting Items to Table {e}")
            db.session.rollback()
            return None
        return True

    @staticmethod
    def get_max_percentile_date():
        latest_record = PercentileModel.query.order_by(PercentileModel.percentile_date.desc()).first()
        return latest_record.percentile_date if latest_record else None

    @staticmethod
    def get_top_n_by_date(n, date=None):
        if date is None:
            latest = db.session.query(db.func.max(PercentileModel.percentile_date)).scalar()
            if not latest:
                return []
        else:
            latest = date
        percentiles = PercentileModel.query.filter(
            PercentileModel.percentile_date == latest
        ).limit(n).all()

        return percentiles

    @staticmethod
    def get_percentiles_by_date(percentile_date):
        return PercentileModel.query.filter(
            PercentileModel.percentile_date == percentile_date
        ).all()

    @staticmethod
    def get_latest_by_symbol(symbol):
        """Get the latest available percentile record for a symbol"""
        return PercentileModel.query.filter(
            PercentileModel.tradingsymbol == symbol
        ).order_by(PercentileModel.percentile_date.desc()).first()

    @staticmethod
    def get_by_date_and_symbol(percentile_date, symbol):
        return PercentileModel.query.filter(
            PercentileModel.percentile_date == percentile_date,
            PercentileModel.tradingsymbol == symbol
        ).all()

    @staticmethod
    def delete_by_tradingsymbol(tradingsymbol: str):
        """Delete all percentile records for a specific tradingsymbol."""
        try:
            num_deleted = PercentileModel.query.filter(
                PercentileModel.tradingsymbol == tradingsymbol
            ).delete()
            db.session.commit()
            return num_deleted
        except SQLAlchemyError as e:
            db.session.rollback()
            return -1

    @staticmethod
    def delete_after_date(date):
        """Delete all percentile records after a given date."""
        try:
            num_deleted = PercentileModel.query.filter(
                PercentileModel.percentile_date > date
            ).delete()
            db.session.commit()
            return num_deleted
        except SQLAlchemyError as e:
            db.session.rollback()
            return -1

    @staticmethod
    def get_all_distinct_dates():
        """Get all distinct percentile dates, ordered ascending.

        Returns:
            List[date]: Sorted list of unique percentile dates.

        Example:
            >>> dates = PercentileRepository.get_all_distinct_dates()
        """
        result = db.session.query(
            PercentileModel.percentile_date
        ).distinct().order_by(
            PercentileModel.percentile_date
        ).all()
        return [r[0] for r in result]
