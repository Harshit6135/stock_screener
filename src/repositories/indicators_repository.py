from db import db
from datetime import datetime
from sqlalchemy import and_, or_, func
from sqlalchemy.exc import SQLAlchemyError

from models import IndicatorsModel


class IndicatorsRepository:

    @staticmethod
    def bulk_insert(indicator_data):
        """Add multiple indicators"""
        try:
            db.session.bulk_insert_mappings(IndicatorsModel, indicator_data, return_defaults=True)
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            return None
        return indicator_data

    @staticmethod
    def query(filter_data):
        query = IndicatorsModel.query
        if not filter_data.get("end_date"):
            filter_data['end_date'] = datetime.now().date()

        instrument_filter = []
        if "instrument_token" in filter_data:
            instrument_filter.append(IndicatorsModel.instrument_token == filter_data["instrument_token"])
        if "tradingsymbol" in filter_data:
            instrument_filter.append(IndicatorsModel.tradingsymbol == filter_data["tradingsymbol"])

        if instrument_filter:
            query = query.filter(or_(*instrument_filter))

        query = query.filter(
            and_(
                IndicatorsModel.date >= filter_data["start_date"],
                IndicatorsModel.date <= filter_data["end_date"],
            )
        )

        return query.all()

    @staticmethod
    def get_latest_date_for_all():
        """Fetch the max date for each instrument"""
        query = db.session.query(
            IndicatorsModel.instrument_token,
            func.max(IndicatorsModel.date).label("max_date")
        ).group_by(IndicatorsModel.instrument_token)

        return query.all()

    @staticmethod
    def get_latest_date_by_symbol(tradingsymbol):
        """Fetch the latest market data for a tradingsymbol"""
        query = IndicatorsModel.query.filter(
            IndicatorsModel.tradingsymbol == tradingsymbol
        )

        return query.order_by(IndicatorsModel.date.desc()).first()

    @staticmethod
    def get_indicators_for_all_stocks(date_range):
        """Fetch the latest market data for a tradingsymbol"""
        query = IndicatorsModel.query
        date_filter = []
        if "start_date" in date_range:
            date_filter.append(IndicatorsModel.date >= date_range["start_date"])
        if "end_date" in date_range:
            date_filter.append(IndicatorsModel.date <= date_range["end_date"])

        if date_filter:
            query = query.filter(and_(*date_filter))

        return query.all()

    @staticmethod
    def delete_by_tradingsymbol(tradingsymbol: str):
        """Delete all market data rows for a specific tradingsymbol."""
        try:
            num_rows_deleted = IndicatorsModel.query.filter(
                IndicatorsModel.tradingsymbol == tradingsymbol
            ).delete()
            db.session.commit()
            return num_rows_deleted
        except SQLAlchemyError as e:
            db.session.rollback()
            return -1

    @staticmethod
    def get_indicator_by_tradingsymbol(indicator, tradingsymbol: str, date=None):
        """Fetch the latest market data for a tradingsymbol, optionally before a specific date"""
        query = IndicatorsModel.query.filter(
            IndicatorsModel.tradingsymbol == tradingsymbol
        )
        if date:
            query = query.filter(IndicatorsModel.date <= date)
            
        query = query.with_entities(getattr(IndicatorsModel, indicator))
        result = query.order_by(IndicatorsModel.date.desc()).first()
        if result:
            return result[0]
        return None

    @staticmethod
    def delete_after_date(date):
        """Delete all indicator records after a given date."""
        try:
            num_deleted = IndicatorsModel.query.filter(
                IndicatorsModel.date > date
            ).delete()
            db.session.commit()
            return num_deleted
        except SQLAlchemyError as e:
            db.session.rollback()
            return -1
