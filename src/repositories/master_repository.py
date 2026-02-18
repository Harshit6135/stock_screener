from db import db
from sqlalchemy.exc import SQLAlchemyError

from models import MasterModel
from config import setup_logger


logger = setup_logger(name="MasterRepository")


class MasterRepository:

    @staticmethod
    def delete_all():
        try:
            num_rows_deleted = MasterModel.query.delete()
            db.session.commit()
            return num_rows_deleted
        except SQLAlchemyError as e:
            logger.error(f"Error deleting master records: {e}")
            db.session.rollback()
            return -1

    @staticmethod
    def bulk_insert(master_data):
        """Add multiple instruments"""
        try:
            db.session.bulk_insert_mappings(MasterModel, master_data, return_defaults=True)
            db.session.commit()
        except SQLAlchemyError as e:
            logger.error(f"Error inserting master records: {e}")
            db.session.rollback()
            return None
        return master_data
