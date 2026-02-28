from db import db
from sqlalchemy.exc import SQLAlchemyError

from models import InstrumentsModel
from models.market_data_model import MarketDataModel


class InstrumentsRepository:

    @staticmethod
    def get_all_instruments():
        instruments = InstrumentsModel.query.all()
        return instruments

    @staticmethod
    def bulk_insert(instrument_data):
        """Add multiple instruments"""
        try:
            db.session.bulk_insert_mappings(InstrumentsModel, instrument_data, return_defaults=True)
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            return None
        return instrument_data

    @staticmethod
    def delete_all():
        try:
            num_rows_deleted = InstrumentsModel.query.delete()
            db.session.commit()
            return num_rows_deleted
        except SQLAlchemyError as e:
            db.session.rollback()
            return -1

    @staticmethod
    def delete_by_token(instrument_token):
        try:
            num_deleted = InstrumentsModel.query.filter_by(instrument_token=instrument_token).delete()
            db.session.commit()
            return num_deleted
        except SQLAlchemyError as e:
            db.session.rollback()
            return -1

    @staticmethod
    def get_by_token(instrument_token):
        instrument = InstrumentsModel.query.get(instrument_token)
        if instrument:
            return instrument
        return None

    @staticmethod
    def get_by_symbol(tradingsymbol):
        return InstrumentsModel.query.filter_by(tradingsymbol=tradingsymbol).first()

    @staticmethod
    def update_instrument(instrument_token, instrument_data):
        instrument = InstrumentsModel.query.get(instrument_token)
        if instrument:
            for field, value in instrument_data.items():
                setattr(instrument, field, value)
            try:
                db.session.commit()
                return instrument
            except SQLAlchemyError as e:
                db.session.rollback()
                return "FAILED"
        return None

    @staticmethod
    def get_token_map():
        """
        Returns a dict keyed by the *base* symbol (tradingsymbol with '-BE' stripped),
        so callers can do O(1) lookups regardless of current series.

        Structure:
          { base_symbol: {
              'instrument_token': int,
              'exchange_token': str,
              'series': str | None,
              'tradingsymbol': str,
              'exchange': str,
          }}
        """
        instruments = InstrumentsModel.query.filter_by(exchange='NSE').all()
        result = {}
        for inst in instruments:
            ts = inst.tradingsymbol or ''
            base = ts[:-3] if ts.endswith('-BE') else ts
            result[base] = {
                'instrument_token': inst.instrument_token,
                'exchange_token': inst.exchange_token,
                'series': inst.series,
                'tradingsymbol': inst.tradingsymbol,
                'exchange': inst.exchange,
            }
        return result

    @staticmethod
    def cascade_token_update(changes):
        """
        For each change dict with keys:
          old_token, new_token, new_exchange_token
        updates market_data and indicators using SQLAlchemy ORM bulk updates.

        Returns number of symbols cascaded.
        """
        if not changes:
            return 0
        try:
            for change in changes:
                old_token = change['old_token']
                new_token = change['new_token']

                # Update market_data rows
                MarketDataModel.query.filter_by(instrument_token=old_token).update(
                    {'instrument_token': new_token},
                    synchronize_session='fetch'
                )

            db.session.commit()
            return len(changes)
        except SQLAlchemyError as e:
            db.session.rollback()
            raise e

    @staticmethod
    def update_instrument_tokens(old_token, new_token, new_exchange_token, new_series, new_tradingsymbol):
        """
        Targeted UPDATE on a single instruments row: update PK (instrument_token),
        exchange_token, series, and tradingsymbol for a symbol whose series changed.

        Since instrument_token is the PK, we delete the old row and insert a new one
        to avoid PK constraint issues.
        """
        try:
            instrument = InstrumentsModel.query.get(old_token)
            if instrument is None:
                return None

            # Capture existing metadata before deleting
            data = {
                'instrument_token': new_token,
                'exchange_token': new_exchange_token,
                'tradingsymbol': new_tradingsymbol,
                'name': instrument.name,
                'exchange': instrument.exchange,
                'series': new_series,
                'market_cap': instrument.market_cap,
                'industry': instrument.industry,
                'sector': instrument.sector,
            }

            db.session.delete(instrument)
            db.session.flush()  # remove old PK before inserting new one

            new_instrument = InstrumentsModel(**data)
            db.session.add(new_instrument)
            db.session.commit()
            return new_instrument
        except SQLAlchemyError as e:
            db.session.rollback()
            raise e
