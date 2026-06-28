from datetime import datetime
from typing import List

from sqlalchemy import and_, func, text
from sqlalchemy.exc import SQLAlchemyError

from db import db
from models import IndicatorsModel


class IndicatorsRepository:

    @staticmethod
    def bulk_insert(indicator_data):
        """Add multiple indicators"""
        try:
            db.session.bulk_insert_mappings(IndicatorsModel, indicator_data, return_defaults=True)
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            return None
        return indicator_data

    @staticmethod
    def query(filter_data):
        query = IndicatorsModel.query
        if not filter_data.get("end_date"):
            filter_data["end_date"] = datetime.now().date()

        if "tradingsymbol" in filter_data:
            query = query.filter(IndicatorsModel.tradingsymbol == filter_data["tradingsymbol"])

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
            IndicatorsModel.tradingsymbol, func.max(IndicatorsModel.date).label("max_date")
        ).group_by(IndicatorsModel.tradingsymbol)

        return query.all()

    @staticmethod
    def get_latest_date_by_symbol(tradingsymbol):
        """Fetch the latest market data for a tradingsymbol"""
        query = IndicatorsModel.query.filter(IndicatorsModel.tradingsymbol == tradingsymbol)

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
        except SQLAlchemyError:
            db.session.rollback()
            return -1

    @staticmethod
    def get_indicator_by_tradingsymbol(indicator, tradingsymbol: str, date=None):
        """Fetch the latest market data for a tradingsymbol, optionally before a specific date"""
        query = IndicatorsModel.query.filter(IndicatorsModel.tradingsymbol == tradingsymbol)
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
            num_deleted = IndicatorsModel.query.filter(IndicatorsModel.date > date).delete()
            db.session.commit()
            return num_deleted
        except SQLAlchemyError:
            db.session.rollback()
            return -1

    @staticmethod
    def bulk_upsert_columns(records: List[dict], columns: List[str]) -> int:
        """Upsert specific columns for existing (tradingsymbol, date) rows.

        For rows that already exist in `indicators`, only the specified columns
        are updated — all other columns are left untouched.
        For (tradingsymbol, date) pairs that do not yet have a row, a sparse
        row is inserted containing just the PK fields and the specified columns.

        Uses SQLite's INSERT OR REPLACE semantics via raw SQL to preserve
        all existing column values when the row already exists:
          1. SELECT existing rows for the batch keys.
          2. Merge requested column values on top.
          3. Bulk-replace the merged rows.

        Args:
            records: List of dicts, each containing at minimum
                     'tradingsymbol', 'date', 'exchange', and the column
                     values for every name in `columns`.
            columns: Column names to write (must be valid IndicatorsModel attrs).

        Returns:
            Number of rows upserted.
        """
        if not records or not columns:
            return 0

        try:
            # Build lookup of incoming values keyed by (tradingsymbol, date)
            incoming = {
                (r["tradingsymbol"], str(r["date"])): r for r in records
            }
            keys = list(incoming.keys())

            # Fetch existing rows for these keys in chunks (SQLite IN limit)
            CHUNK = 900
            existing_map: dict = {}
            for i in range(0, len(keys), CHUNK):
                chunk_keys = keys[i : i + CHUNK]
                symbols = list({k[0] for k in chunk_keys})
                dates = list({k[1] for k in chunk_keys})
                rows = (
                    IndicatorsModel.query
                    .filter(
                        IndicatorsModel.tradingsymbol.in_(symbols),
                        db.cast(IndicatorsModel.date, db.String).in_(dates),
                    )
                    .all()
                )
                for row in rows:
                    row_dict = {
                        c.name: getattr(row, c.name)
                        for c in row.__table__.columns
                    }
                    existing_map[(row.tradingsymbol, str(row.date))] = row_dict

            # Merge: start from existing (or minimal skeleton), patch columns
            merged = []
            for key, new_vals in incoming.items():
                if key in existing_map:
                    row_data = dict(existing_map[key])  # copy all existing cols
                else:
                    # Brand-new row: fill only PK + exchange to keep NOT NULL happy
                    row_data = {
                        "tradingsymbol": new_vals["tradingsymbol"],
                        "date": new_vals["date"],
                        "exchange": new_vals.get("exchange", ""),
                    }
                # Overwrite just the requested columns
                for col in columns:
                    if col in new_vals:
                        row_data[col] = new_vals[col]
                merged.append(row_data)

            # Bulk replace (INSERT OR REPLACE in SQLite)
            db.session.bulk_insert_mappings(
                IndicatorsModel, merged, return_defaults=False
            )
            db.session.commit()
            return len(merged)

        except SQLAlchemyError as exc:
            db.session.rollback()
            raise exc
