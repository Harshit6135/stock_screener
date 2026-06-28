from sqlalchemy.exc import SQLAlchemyError

from config import setup_logger
from db import db
from models import PercentileModel

logger = setup_logger(name="PercentileRepository")


class PercentileRepository:
    """Repository for percentile rank operations (renamed from RankingRepository)"""

    @staticmethod
    def bulk_insert(percentile_records):
        try:
            db.session.bulk_insert_mappings(
                PercentileModel, percentile_records, return_defaults=True
            )
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            logger.error(f"Error inserting Items to Table {e}")
            return None
        return percentile_records

    @staticmethod
    def delete(percentile_date, strategy_id: str = "strategy1"):
        try:
            db.session.query(PercentileModel).filter(
                PercentileModel.percentile_date == percentile_date,
                PercentileModel.strategy_id == strategy_id,
            ).delete()
            db.session.commit()
        except SQLAlchemyError as e:
            logger.error(f"Error deleting Items to Table {e}")
            db.session.rollback()
            return None
        return True

    @staticmethod
    def get_max_percentile_date(strategy_id: str = "strategy1"):
        latest_record = (
            PercentileModel.query
            .filter(PercentileModel.strategy_id == strategy_id)
            .order_by(PercentileModel.percentile_date.desc())
            .first()
        )
        return latest_record.percentile_date if latest_record else None

    @staticmethod
    def get_top_n_by_date(n, date=None, strategy_id: str = "strategy1"):
        if date is None:
            latest = db.session.query(db.func.max(PercentileModel.percentile_date)).filter(
                PercentileModel.strategy_id == strategy_id
            ).scalar()
            if not latest:
                return []
        else:
            latest = date
        percentiles = (
            PercentileModel.query
            .filter(
                PercentileModel.percentile_date == latest,
                PercentileModel.strategy_id == strategy_id,
            )
            .limit(n)
            .all()
        )
        return percentiles

    @staticmethod
    def get_percentiles_by_date(percentile_date, strategy_id: str = "strategy1"):
        return PercentileModel.query.filter(
            PercentileModel.percentile_date == percentile_date,
            PercentileModel.strategy_id == strategy_id,
        ).all()

    @staticmethod
    def get_latest_by_symbol(symbol):
        """Get the latest available percentile record for a symbol"""
        return (
            PercentileModel.query.filter(PercentileModel.tradingsymbol == symbol)
            .order_by(PercentileModel.percentile_date.desc())
            .first()
        )

    @staticmethod
    def get_by_date_and_symbol(percentile_date, symbol):
        return PercentileModel.query.filter(
            PercentileModel.percentile_date == percentile_date,
            PercentileModel.tradingsymbol == symbol,
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
        except SQLAlchemyError:
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
        except SQLAlchemyError:
            db.session.rollback()
            return -1

    @staticmethod
    def get_all_distinct_dates(strategy_id: str = "strategy1"):
        """Get all distinct percentile dates, ordered ascending."""
        result = (
            db.session.query(PercentileModel.percentile_date)
            .filter(PercentileModel.strategy_id == strategy_id)
            .distinct()
            .order_by(PercentileModel.percentile_date)
            .all()
        )
        return [r[0] for r in result]

    @staticmethod
    def get_percentiles_after_date(after_date=None, strategy_id: str = "strategy1"):
        """Fetch all percentile records after a given date.

        Parameters:
            after_date: Date to start from (exclusive).
                If None, returns all records.
            strategy_id: Filter to this strategy's rows only.

        Returns:
            List of PercentileModel records.
        """
        query = PercentileModel.query.filter(
            PercentileModel.strategy_id == strategy_id
        )
        if after_date is not None:
            query = query.filter(PercentileModel.percentile_date > after_date)
        return query.order_by(PercentileModel.percentile_date).all()
