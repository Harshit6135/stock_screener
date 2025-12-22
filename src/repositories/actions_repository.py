from db import db
from sqlalchemy.exc import SQLAlchemyError

from models import ActionsModel


class ActionsRepository:

    @staticmethod
    def get_pending_actions():
        return ActionsModel.query.filter_by(executed=False).order_by(
            ActionsModel.action_date.desc()
        ).all()

    @staticmethod
    def bulk_insert(actions):
        """Add multiple indicators"""
        try:
            db.session.bulk_insert_mappings(ActionsModel, actions, return_defaults=True)
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            return None
        return actions

    @staticmethod
    def get_action_by_action_id(action_id):
        return ActionsModel.query.filter_by(action_id=action_id).first()

    @staticmethod
    def update_action_columns(action_id, column_data):
        """Update multiple columns for a given action_id."""
        query = ActionsModel.query.filter_by(action_id=action_id)
        query.update(column_data)
        db.session.commit()
        return query.first()