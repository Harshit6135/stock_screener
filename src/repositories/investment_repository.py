"""
Investment Repository

Data access layer for holdings and portfolio summary.
Actions moved to repositories/actions_repository.py for better separation.
"""
from typing import Optional
from db import db
from sqlalchemy import func
from sqlalchemy.orm import Session
from models import InvestmentHoldingsModel, InvestmentSummaryModel
from config import setup_logger

logger = setup_logger(name="InvestmentRepository")


class InvestmentRepository:
    """
    Repository for investment holdings and summary data.
    
    All methods accept optional `session` parameter:
    - session=None → uses default session (personal.db)
    - session=backtest_session → writes to backtest.db
    """

    @staticmethod
    def _get_session(session: Optional[Session] = None) -> Session:
        """Get session to use - default or injected."""
        return session if session is not None else db.session

    @staticmethod
    def get_holdings_dates(session: Optional[Session] = None):
        """
        Get distinct working dates from holdings table.
        
        Parameters:
            session (Optional[Session]): Database session to use
        
        Returns:
            list: Working dates in descending order
        """
        sess = InvestmentRepository._get_session(session)
        dates = sess.query(
            InvestmentHoldingsModel.working_date
        ).distinct().order_by(
            InvestmentHoldingsModel.working_date.desc()
        ).all()
        return [d[0] for d in dates]

    @staticmethod
    def get_holdings(working_date=None, session: Optional[Session] = None):
        """
        Get all holdings for a given working date.
        
        Parameters:
            working_date: Date to query, defaults to latest
            session (Optional[Session]): Database session to use
        
        Returns:
            list: InvestmentHoldingsModel instances
        """
        sess = InvestmentRepository._get_session(session)
        if not working_date:
            working_date = sess.query(func.max(InvestmentHoldingsModel.working_date)).scalar()
        return sess.query(InvestmentHoldingsModel).filter(
            InvestmentHoldingsModel.working_date == working_date
        ).all()

    @staticmethod
    def get_holdings_by_symbol(symbol, working_date=None, session: Optional[Session] = None):
        """
        Get holding for a specific symbol and date.
        
        Parameters:
            symbol (str): Trading symbol
            working_date: Date to query, defaults to latest
            session (Optional[Session]): Database session to use
        
        Returns:
            InvestmentHoldingsModel: Holding instance or None
        """
        sess = InvestmentRepository._get_session(session)
        if not working_date:
            working_date = sess.query(func.max(InvestmentHoldingsModel.working_date)).scalar()
        return sess.query(InvestmentHoldingsModel).filter(
            InvestmentHoldingsModel.working_date == working_date,
            InvestmentHoldingsModel.symbol == symbol
        ).first()

    @staticmethod
    def get_summary(working_date=None, session: Optional[Session] = None):
        """
        Get portfolio summary for a given date.
        
        Parameters:
            working_date: Date to query, defaults to latest
            session (Optional[Session]): Database session to use
        
        Returns:
            InvestmentSummaryModel: Summary instance or None
        """
        sess = InvestmentRepository._get_session(session)
        if not working_date:
            working_date = sess.query(func.max(InvestmentSummaryModel.working_date)).scalar()
        return sess.query(InvestmentSummaryModel).filter(
            InvestmentSummaryModel.working_date == working_date
        ).first()

    @staticmethod
    def bulk_insert_holdings(holdings, session: Optional[Session] = None):
        """
        Insert holdings with optional session injection for backtest.
        
        Parameters:
            holdings (list): List of holding dictionaries
            session (Optional[Session]): Database session to use
        
        Returns:
            bool: True if successful, None otherwise
        """
        sess = InvestmentRepository._get_session(session)
        try:
            sess.query(InvestmentHoldingsModel).filter(
                InvestmentHoldingsModel.working_date == holdings[0]['working_date']
            ).delete()
            sess.commit()
        except Exception as e:
            logger.error(f"Error bulk_insert_holdings (delete) {e}")
            sess.rollback()

        try:
            sess.bulk_insert_mappings(InvestmentHoldingsModel, holdings, return_defaults=True)
            sess.commit()
        except Exception as e:
            logger.error(f"Error bulk_insert_holdings {e}")
            sess.rollback()
            return None
        return True

    @staticmethod
    def insert_summary(summary, session: Optional[Session] = None):
        """
        Insert summary with optional session injection for backtest.
        
        Parameters:
            summary (dict): Summary data
            session (Optional[Session]): Database session to use
        
        Returns:
            bool: True if successful, None otherwise
        """
        sess = InvestmentRepository._get_session(session)
        summary_data = InvestmentSummaryModel(**summary)
        try:
            sess.query(InvestmentSummaryModel).filter(
                InvestmentSummaryModel.working_date == summary['working_date']
            ).delete()
            sess.commit()
        except Exception as e:
            logger.error(f"Error deleting summary {e}")
            sess.rollback()

        try:
            sess.add(summary_data)
            sess.commit()
            return True
        except Exception as e:
            logger.error(f"Error inserting summary {e}")
            sess.rollback()
            return None

    @staticmethod
    def delete_holdings(working_date, session: Optional[Session] = None):
        """
        Delete holdings for a specific date.
        
        Parameters:
            working_date: Date to delete
            session (Optional[Session]): Database session to use
        """
        sess = InvestmentRepository._get_session(session)
        try:
            sess.query(InvestmentHoldingsModel).filter(
                InvestmentHoldingsModel.working_date == working_date
            ).delete()
            sess.commit()
        except Exception as e:
            logger.error(f"Error delete_holdings {e}")
            sess.rollback()

    @staticmethod
    def delete_summary(working_date, session: Optional[Session] = None):
        """
        Delete summary for a specific date.
        
        Parameters:
            working_date: Date to delete
            session (Optional[Session]): Database session to use
        """
        sess = InvestmentRepository._get_session(session)
        try:
            sess.query(InvestmentSummaryModel).filter(
                InvestmentSummaryModel.working_date == working_date
            ).delete()
            sess.commit()
        except Exception as e:
            logger.error(f"Error delete_summary {e}")
            sess.rollback()

    @staticmethod
    def delete_all_holdings(session: Optional[Session] = None):
        """
        Delete all holdings (used in cleanup operations).
        
        Parameters:
            session (Optional[Session]): Database session to use
        """
        sess = InvestmentRepository._get_session(session)
        try:
            sess.query(InvestmentHoldingsModel).delete()
            sess.commit()
        except Exception as e:
            logger.error(f"Error delete_all_holdings {e}")
            sess.rollback()

    @staticmethod
    def delete_all_summary(session: Optional[Session] = None):
        """
        Delete all summary records (used in cleanup operations).
        
        Parameters:
            session (Optional[Session]): Database session to use
        """
        sess = InvestmentRepository._get_session(session)
        try:
            sess.query(InvestmentSummaryModel).delete()
            sess.commit()
        except Exception as e:
            logger.error(f"Error deleting all summary {e}")
            sess.rollback()