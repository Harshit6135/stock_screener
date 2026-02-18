from db import db
from datetime import datetime
from sqlalchemy import and_, or_, func
from sqlalchemy.exc import SQLAlchemyError

from models import MarketDataModel


class MarketDataRepository:
    
    @staticmethod
    def bulk_insert(market_data):
        try:
            db.session.bulk_insert_mappings(MarketDataModel, market_data, return_defaults=True)
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            return None
        return market_data

    @staticmethod
    def query(filter_data):
        query = MarketDataModel.query
        if not filter_data.get("end_date"):
            filter_data['end_date'] = datetime.now().date()

        instrument_filter = []
        if "instrument_token" in filter_data:
            instrument_filter.append(MarketDataModel.instrument_token == filter_data["instrument_token"])
        if "tradingsymbol" in filter_data:
            instrument_filter.append(MarketDataModel.tradingsymbol == filter_data["tradingsymbol"])

        if instrument_filter:
            query = query.filter(or_(*instrument_filter))

        query = query.filter(
            and_(
                MarketDataModel.date >= filter_data["start_date"],
                MarketDataModel.date <= filter_data["end_date"],
            )
        )

        return query.all()

    @staticmethod
    def get_latest_date_for_all():
        """Fetch the max date for each instrument"""
        query = db.session.query(
            MarketDataModel.instrument_token,
            func.max(MarketDataModel.date).label("max_date")
        ).group_by(MarketDataModel.instrument_token)
        return query.all()

    @staticmethod
    def get_latest_date_by_symbol(tradingsymbol):
        """Fetch the latest market data for a tradingsymbol"""
        query = MarketDataModel.query.filter(
            MarketDataModel.tradingsymbol == tradingsymbol
        )

        return query.order_by(MarketDataModel.date.desc()).first()

    @staticmethod
    def get_latest_marketdata(tradingsymbol):
        """Fetch the latest market data for a tradingsymbol (alias)"""
        return MarketDataRepository.get_latest_date_by_symbol(tradingsymbol)

    @staticmethod
    def get_prices_for_all_stocks(date_range):
        """Fetch the latest market data for a tradingsymbol"""
        query = MarketDataModel.query
        date_filter = []
        if "start_date" in date_range:
            date_filter.append(MarketDataModel.date >= date_range["start_date"])
        if "end_date" in date_range:
            date_filter.append(MarketDataModel.date <= date_range["end_date"])

        if date_filter:
            query = query.filter(and_(*date_filter))

        return query.all()

    @staticmethod
    def delete_by_tradingsymbol(tradingsymbol: str):
        """Delete all market data rows for a specific tradingsymbol."""
        try:
            num_rows_deleted = MarketDataModel.query.filter(
                MarketDataModel.tradingsymbol == tradingsymbol
            ).delete()
            db.session.commit()
            return num_rows_deleted
        except SQLAlchemyError as e:
            db.session.rollback()
            return -1

    @staticmethod
    def get_max_date_from_table():
        """Fetch the absolute maximum date present in the MarketDataModel table."""
        return db.session.query(func.max(MarketDataModel.date)).scalar()

    @staticmethod
    def get_min_date_from_table():
        """Fetch the absolute minimum date present in the MarketDataModel table."""
        return db.session.query(func.min(MarketDataModel.date)).scalar()

    @staticmethod
    def get_marketdata_first_day(tradingsymbol:str, date):
        """Fetch market data for a tradingsymbol, on a specific date"""
        return MarketDataModel.query.filter(
            MarketDataModel.tradingsymbol == tradingsymbol,
            MarketDataModel.date >= date,
            MarketDataModel.date <= datetime.now().date()
        ).order_by(MarketDataModel.date.asc()).first()

    @staticmethod
    def get_marketdata_by_trading_symbol(tradingsymbol:str, date):
        """Fetch market data for a tradingsymbol, on a specific date"""
        query = MarketDataModel.query.filter(
            MarketDataModel.tradingsymbol == tradingsymbol,
            MarketDataModel.date <= date
        )
        return query.order_by(MarketDataModel.date.desc()).first()

    @staticmethod
    def delete_after_date(date):
        """Delete all market data records after a given date."""
        try:
            num_deleted = MarketDataModel.query.filter(
                MarketDataModel.date > date
            ).delete()
            db.session.commit()
            return num_deleted
        except SQLAlchemyError as e:
            db.session.rollback()
            return -1
