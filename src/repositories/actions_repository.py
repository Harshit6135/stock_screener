"""
Actions Repository

Data access layer for trading actions.
Supports session injection for multi-database (personal/backtest) operations.
"""
from typing import Optional
from db import db
from sqlalchemy import func
from sqlalchemy.orm import Session
from models import ActionsModel
from config import setup_logger

logger = setup_logger(name="ActionsRepository")


class ActionsRepository:
    """
    Repository for trading actions data.
    """

    def __init__(self, session: Optional[Session] = None):
        self.session = self._get_session(session)

    @staticmethod
    def _get_session(session: Optional[Session] = None) -> Session:
        """Get session to use - default or injected."""
        return session if session is not None else db.session

    def get_action_dates(self):
        """
        Get distinct action dates from actions table.
        
        Returns:
            list: action dates in descending order
        """
        dates = self.session.query(
            ActionsModel.action_date
        ).distinct().order_by(
            ActionsModel.action_date.desc()
        ).all()
        return [d[0] for d in dates]

    def get_actions(self, action_date=None):
        """
        Get all actions for a given action date.
        
        Parameters:
            action_date: Date to query, defaults to latest
        
        Returns:
            list: ActionsModel instances
        """
        if not action_date:
            action_date = self.session.query(
                func.max(ActionsModel.action_date)
            ).scalar()
        return self.session.query(ActionsModel).filter(
            ActionsModel.action_date == action_date
        ).all()

    def get_action_by_symbol(self, symbol, action_date=None):
        """
        Get action for a specific symbol and date.
        
        Parameters:
            symbol (str): Trading symbol
            action_date: Date to query, defaults to latest
        
        Returns:
            ActionsModel: Action instance or None
        """
        if not action_date:
            action_date = self.session.query(func.max(ActionsModel.action_date)).scalar()
        return self.session.query(ActionsModel).filter(
            ActionsModel.action_date == action_date,
            ActionsModel.symbol == symbol
        ).first()

    def bulk_insert_actions(self, actions):
        """
        Bulk insert action records.
        
        Parameters:
            actions (list): List of action dictionaries
        
        Returns:
            bool: True if successful, None otherwise
        """
        if not actions:
            return True
        try:
            self.session.bulk_insert_mappings(ActionsModel, actions, return_defaults=True)
            self.session.commit()
        except Exception as e:
            logger.error(f"Error bulk_insert_actions {e}")
            self.session.rollback()
            return None
        return True

    def delete_actions(self, action_date):
        """
        Delete actions for a specific date.
        
        Parameters:
            action_date: Date to delete actions for
        """
        try:
            self.session.query(ActionsModel).filter(
                ActionsModel.action_date == action_date
            ).delete()
            self.session.commit()
        except Exception as e:
            logger.error(f"Error delete_actions {e}")
            self.session.rollback()

    def check_other_pending_actions(self, action_date):
        """
        Check for pending actions on other dates.
        
        Parameters:
            action_date: Date to exclude from check
        
        Returns:
            list: Pending actions from other dates
        """
        return self.session.query(ActionsModel).filter(
            ActionsModel.action_date != action_date,
            ActionsModel.status == 'Pending'
        ).all()

    def update_action(self, action_data):
        """
        Update an action (typically for approval/rejection).
        
        Parameters:
            action_data (dict): Action data with action_id and fields to update
        
        Returns:
            bool: True if successful, None otherwise
        """
        action_id = action_data['action_id']
        if action_data['status'] == 'Approved':
            if 'execution_price' not in action_data:
                logger.warning('Missing execution price for approval')
                return None
        try:
            action = self.session.query(ActionsModel).filter(
                ActionsModel.action_id == action_id
            ).first()
            if action:
                for key, value in action_data.items():
                    if hasattr(action, key):
                        setattr(action, key, value)
                self.session.commit()
                return True
            else:
                logger.warning(f"Action with id {action_id} not found")
                return None
        except Exception as e:
            logger.error(f"Error updating action {e}")
            self.session.rollback()
            return None

    def get_pending_actions(self):
        """
        Get all pending actions across all dates.
        
        Returns:
            list: Pending ActionsModel instances
        """
        return self.session.query(ActionsModel).filter(
            ActionsModel.status == 'Pending'
        ).all()

    def get_all_approved_actions(self):
        """
        Get all approved actions ordered by date descending.
        Used for trade journal.
        
        Returns:
            list: Approved ActionsModel instances
        """
        return self.session.query(ActionsModel).filter(
            ActionsModel.status == 'Approved'
        ).order_by(
            ActionsModel.action_date.desc()
        ).all()

    def insert_action(self, action_dict):
        """
        Insert a single action without deleting existing actions for that date.
        Used for mid-week SL sells and pending buy fills.
        
        Parameters:
            action_dict (dict): Action data dictionary
        
        Returns:
            ActionsModel: Inserted action or None on error
        """
        try:
            action = ActionsModel(**action_dict)
            self.session.add(action)
            self.session.commit()
            return action
        except Exception as e:
            logger.error(f"Error insert_action: {e}")
            self.session.rollback()
            return None

    def delete_all_actions(self):
        """
        Delete all actions (used in cleanup operations).
        """
        try:
            self.session.query(ActionsModel).delete()
            self.session.commit()
        except Exception as e:
            logger.error(f"Error delete_all_actions {e}")
            self.session.rollback()
