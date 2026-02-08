"""
Actions Repository

Data access layer for trading actions.
Supports session injection for multi-database (personal/backtest) operations.
Separated from investment repository for better modularity.
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
    
    All methods accept optional `session` parameter:
    - session=None → uses default session (personal.db)
    - session=backtest_session → writes to backtest.db
    """

    @staticmethod
    def _get_session(session: Optional[Session] = None) -> Session:
        """Get session to use - default or injected."""
        return session if session is not None else db.session

    @staticmethod
    def get_action_dates(session: Optional[Session] = None):
        """
        Get distinct working dates from actions table.
        
        Parameters:
            session (Optional[Session]): Database session to use
        
        Returns:
            list: Working dates in descending order
        """
        sess = ActionsRepository._get_session(session)
        dates = sess.query(
            ActionsModel.working_date
        ).distinct().order_by(
            ActionsModel.working_date.desc()
        ).all()
        return [d[0] for d in dates]

    @staticmethod
    def get_actions(working_date=None, session: Optional[Session] = None):
        """
        Get all actions for a given working date.
        
        Parameters:
            working_date: Date to query, defaults to latest
            session (Optional[Session]): Database session to use
        
        Returns:
            list: ActionsModel instances
        """
        sess = ActionsRepository._get_session(session)
        if not working_date:
            working_date = sess.query(
                func.max(ActionsModel.working_date)
            ).scalar()
        return sess.query(ActionsModel).filter(
            ActionsModel.working_date == working_date
        ).all()

    @staticmethod
    def get_action_by_symbol(symbol, working_date=None, session: Optional[Session] = None):
        """
        Get action for a specific symbol and date.
        
        Parameters:
            symbol (str): Trading symbol
            working_date: Date to query, defaults to latest
            session (Optional[Session]): Database session to use
        
        Returns:
            ActionsModel: Action instance or None
        """
        sess = ActionsRepository._get_session(session)
        if not working_date:
            working_date = sess.query(func.max(ActionsModel.working_date)).scalar()
        return sess.query(ActionsModel).filter(
            ActionsModel.working_date == working_date,
            ActionsModel.symbol == symbol
        ).first()

    @staticmethod
    def bulk_insert_actions(actions, session: Optional[Session] = None):
        """
        Insert actions with optional session injection for backtest.
        
        Parameters:
            actions (list): List of action dictionaries
            session (Optional[Session]): Database session to use
        
        Returns:
            bool: True if successful, None otherwise
        """
        sess = ActionsRepository._get_session(session)
        try:
            sess.query(ActionsModel).filter(
                ActionsModel.working_date == actions[0]['working_date']
            ).delete()
            sess.commit()
        except Exception as e:
            logger.error(f"Error bulk_insert_actions (delete) {e}")
            sess.rollback()

        try:
            sess.bulk_insert_mappings(ActionsModel, actions, return_defaults=True)
            sess.commit()
        except Exception as e:
            logger.error(f"Error bulk_insert_actions {e}")
            sess.rollback()
            return None
        return True

    @staticmethod
    def check_other_pending_actions(working_date, session: Optional[Session] = None):
        """
        Check for pending actions on other dates.
        
        Parameters:
            working_date: Date to exclude from check
            session (Optional[Session]): Database session to use
        
        Returns:
            list: Pending actions from other dates
        """
        sess = ActionsRepository._get_session(session)
        return sess.query(ActionsModel).filter(
            ActionsModel.working_date != working_date,
            ActionsModel.status == 'Pending'
        ).all()

    @staticmethod
    def update_action(action_data, session: Optional[Session] = None):
        """
        Update an action (typically for approval/rejection).
        
        Parameters:
            action_data (dict): Action data with action_id and fields to update
            session (Optional[Session]): Database session to use
        
        Returns:
            bool: True if successful, None otherwise
        """
        sess = ActionsRepository._get_session(session)
        action_id = action_data['action_id']
        if action_data['status'] == 'Approved':
            if 'execution_price' not in action_data:
                logger.warning('Missing execution price for approval')
                return None
        try:
            action = sess.query(ActionsModel).filter(
                ActionsModel.action_id == action_id
            ).first()
            if action:
                for key, value in action_data.items():
                    if hasattr(action, key):
                        setattr(action, key, value)
                sess.commit()
                return True
            else:
                logger.warning(f"Action with id {action_id} not found")
                return None
        except Exception as e:
            logger.error(f"Error updating action {e}")
            sess.rollback()
            return None

    @staticmethod
    def delete_all_actions(session: Optional[Session] = None):
        """
        Delete all actions (used in cleanup operations).
        
        Parameters:
            session (Optional[Session]): Database session to use
        """
        sess = ActionsRepository._get_session(session)
        try:
            sess.query(ActionsModel).delete()
            sess.commit()
        except Exception as e:
            logger.error(f"Error delete_all_actions {e}")
            sess.rollback()
