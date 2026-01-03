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
    def add(action_data):
        """Add a single action"""
        try:
            action = ActionsModel(**action_data)
            db.session.add(action)
            db.session.commit()
            return action
        except SQLAlchemyError:
            db.session.rollback()
            return None

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
    def delete_actions(working_date):
        try:
            ActionsModel.query.filter(ActionsModel.action_date == working_date).delete()
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            return None

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

    @staticmethod
    def delete_actions_all():
        try:
            ActionsModel.query.delete()
            db.session.commit()
            return None
        except SQLAlchemyError:
            db.session.rollback()
            return None