from db import db
from sqlalchemy.exc import SQLAlchemyError

from models import InstrumentModel


class InstrumentsRepository:

    @staticmethod
    def get_all_instruments():
        instruments = InstrumentModel.query.all()
        return instruments

    @staticmethod
    def bulk_insert(instrument_data):
        """Add multiple instruments"""
        try:
            db.session.bulk_insert_mappings(InstrumentModel, instrument_data, return_defaults=True)
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            return None
        return instrument_data

    @staticmethod
    def delete_all():
        try:
            num_rows_deleted = InstrumentModel.query.delete()
            db.session.commit()
            return num_rows_deleted
        except SQLAlchemyError as e:
            db.session.rollback()
            return -1

    @staticmethod
    def get_by_token(instrument_token):
        instrument = InstrumentModel.query.get(instrument_token)
        if instrument:
            return instrument
        return None

    @staticmethod
    def update_instrument(instrument_token, instrument_data):
        instrument = InstrumentModel.query.get(instrument_token)
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
