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
    def get_symbols_with_null_columns(columns: List[str]) -> set:
        """Return symbols whose LATEST indicator row has at least one NULL
        in any of the given indicator columns.

        Checks only the most recent row per symbol (by max date) rather than
        scanning all historical rows. This prevents a false-positive loop where
        very old rows (e.g. pre-2015) have NULL mansfield_rs because benchmark
        data doesn't reach that far back.

        Args:
            columns: List of IndicatorsModel column names to check.

        Returns:
            Set of tradingsymbol strings that need patching.
        """
        if not columns:
            return set()

        # Build IS NULL filters for each column, guarding against unknown attrs
        null_filters = []
        for col in columns:
            attr = getattr(IndicatorsModel, col, None)
            if attr is not None:
                null_filters.append(attr.is_(None))

        if not null_filters:
            return set()

        from sqlalchemy import func, or_

        # Subquery: latest date per symbol
        latest_dates = (
            db.session.query(
                IndicatorsModel.tradingsymbol,
                func.max(IndicatorsModel.date).label("max_date"),
            )
            .group_by(IndicatorsModel.tradingsymbol)
            .subquery()
        )

        # Join to get the latest row per symbol, then filter for any NULL column
        rows = (
            db.session.query(IndicatorsModel.tradingsymbol)
            .join(
                latest_dates,
                (IndicatorsModel.tradingsymbol == latest_dates.c.tradingsymbol)
                & (IndicatorsModel.date == latest_dates.c.max_date),
            )
            .filter(or_(*null_filters))
            .distinct()
            .all()
        )
        return {r.tradingsymbol for r in rows}

    @staticmethod
    def bulk_upsert_columns(records: List[dict], columns: List[str]) -> int:
        """Upsert specific columns for existing (tradingsymbol, date) rows.

        For rows that already exist in ``indicators``, only the specified columns
        are updated — all other columns are left untouched.
        For (tradingsymbol, date) pairs that do not yet have a row, a sparse
        row is inserted containing just the PK fields and the specified columns.

        Uses a two-step approach:
          1. Fetch all existing rows for the batch's symbols.
          2. Merge requested column values on top of the full existing row.
          3. Write via INSERT OR REPLACE (SQLite handles conflicts atomically).

        Args:
            records: List of dicts, each containing at minimum
                     'tradingsymbol', 'date', 'exchange', and the column
                     values for every name in ``columns``.
            columns: Column names to write (must be valid IndicatorsModel attrs).

        Returns:
            Number of rows upserted.
        """
        if not records or not columns:
            return 0

        try:
            from sqlalchemy import insert as sa_insert

            # Build lookup of incoming values keyed by (tradingsymbol, str(date))
            incoming = {
                (r["tradingsymbol"], str(r["date"])): r for r in records
            }

            # Fetch all existing rows for the symbols in this batch in one query
            symbols_in_batch = list({r["tradingsymbol"] for r in records})
            existing_rows = (
                IndicatorsModel.query
                .filter(IndicatorsModel.tradingsymbol.in_(symbols_in_batch))
                .all()
            )
            existing_map: dict = {
                (row.tradingsymbol, str(row.date)): {
                    c.name: getattr(row, c.name)
                    for c in row.__table__.columns
                }
                for row in existing_rows
            }

            # Merge: start from existing full row (or minimal skeleton),
            # then overwrite just the requested columns.
            merged = []
            for key, new_vals in incoming.items():
                if key in existing_map:
                    row_data = dict(existing_map[key])
                else:
                    row_data = {
                        "tradingsymbol": new_vals["tradingsymbol"],
                        "date": new_vals["date"],
                        "exchange": new_vals.get("exchange", ""),
                    }
                for col in columns:
                    if col in new_vals:
                        row_data[col] = new_vals[col]
                merged.append(row_data)

            if not merged:
                return 0

            # INSERT OR REPLACE — SQLite resolves UNIQUE conflicts by replacing
            # the row atomically, preserving all columns in the merged dict.
            stmt = sa_insert(IndicatorsModel).prefix_with("OR REPLACE")
            db.session.execute(stmt, merged)
            db.session.commit()
            return len(merged)

        except Exception as exc:
            db.session.rollback()
            raise exc

