"""
Investment Repository

Data access layer for holdings and portfolio summary.
Actions moved to repositories/actions_repository.py for better separation.
"""
from typing import Optional
from db import db
from sqlalchemy import func
from sqlalchemy.orm import Session
from models import InvestmentsHoldingsModel, InvestmentsSummaryModel
from config import setup_logger

logger = setup_logger(name="InvestmentRepository")


class InvestmentRepository:
    """
    Repository for investment holdings and summary data.
    """

    def __init__(self, session: Optional[Session] = None):
        self.session = self._get_session(session)

    @staticmethod
    def _get_session(session: Optional[Session] = None) -> Session:
        """Get session to use - default or injected."""
        return session if session is not None else db.session

    def get_holdings_dates(self):
        """
        Get distinct dates from holdings table.

        Returns:
            list: dates in descending order
        """
        dates = self.session.query(
            InvestmentsHoldingsModel.date
        ).distinct().order_by(
            InvestmentsHoldingsModel.date.desc()
        ).all()
        return [d[0] for d in dates]

    def get_holdings(self, date=None):
        """
        Get all holdings for a given date.
        
        Parameters:
            date: Date to query, defaults to latest
        
        Returns:
            list: InvestmentsHoldingsModel instances
        """
        if not date:
            date = self.session.query(func.max(InvestmentsHoldingsModel.date)).scalar()
        return self.session.query(InvestmentsHoldingsModel).filter(
            InvestmentsHoldingsModel.date == date
        ).all()

    def get_holdings_by_symbol(self, symbol, date=None):
        """
        Get holding for a specific symbol and date.
        
        Parameters:
            symbol (str): Trading symbol
            date: Date to query, defaults to latest
        
        Returns:
            InvestmentsHoldingsModel: Holding instance or None
        """
        if not date:
            date = self.session.query(func.max(InvestmentsHoldingsModel.date)).scalar()
        return self.session.query(InvestmentsHoldingsModel).filter(
            InvestmentsHoldingsModel.date == date,
            InvestmentsHoldingsModel.symbol == symbol
        ).first()

    def get_summary(self, date=None):
        """
        Get portfolio summary for a given date.
        
        Parameters:
            date: Date to query, defaults to latest
        
        Returns:
            InvestmentsSummaryModel: Summary instance or None
        """
        if not date:
            date = self.session.query(func.max(InvestmentsSummaryModel.date)).scalar()
        return self.session.query(InvestmentsSummaryModel).filter(
            InvestmentsSummaryModel.date == date
        ).first()

    def bulk_insert_holdings(self, holdings):
        """
        Bulk insert holdings records.
        
        Parameters:
            holdings (list): List of holding dictionaries
        
        Returns:
            bool: True if successful, None otherwise
        """
        if not holdings:
            return True
        try:
            self.session.bulk_insert_mappings(InvestmentsHoldingsModel, holdings, return_defaults=True)
            self.session.commit()
        except Exception as e:
            logger.error(f"Error bulk_insert_holdings {e}")
            self.session.rollback()
            return None
        return True

    def insert_summary(self, summary):
        """
        Insert summary with optional session injection for backtest.
        
        Parameters:
            summary (dict): Summary data
        
        Returns:
            bool: True if successful, None otherwise
        """
        summary_data = InvestmentsSummaryModel(**summary)
        try:
            self.session.query(InvestmentsSummaryModel).filter(
                InvestmentsSummaryModel.date == summary['date']
            ).delete()
            self.session.commit()
        except Exception as e:
            logger.error(f"Error deleting summary {e}")
            self.session.rollback()

        try:
            self.session.add(summary_data)
            self.session.commit()
            return True
        except Exception as e:
            logger.error(f"Error inserting summary {e}")
            self.session.rollback()
            return None

    def delete_holdings(self, date):
        """
        Delete holdings for a specific date.
        
        Parameters:
            date: Date to delete
        """
        try:
            self.session.query(InvestmentsHoldingsModel).filter(
                InvestmentsHoldingsModel.date == date
            ).delete()
            self.session.commit()
        except Exception as e:
            logger.error(f"Error delete_holdings {e}")
            self.session.rollback()

    def delete_holding(self, symbol, date):
        """
        Delete a single holding for a specific symbol and date.
        
        Parameters:
            symbol (str): Trading symbol
            date (date): Date of the holding
        """
        try:
            self.session.query(InvestmentsHoldingsModel).filter(
                InvestmentsHoldingsModel.date == date,
                InvestmentsHoldingsModel.symbol == symbol
            ).delete()
            self.session.commit()
        except Exception as e:
            logger.error(f"Error delete_holding {e}")
            self.session.rollback()

    def delete_summary(self, date):
        """
        Delete summary for a specific date.
        
        Parameters:
            date: Date to delete
        """
        try:
            self.session.query(InvestmentsSummaryModel).filter(
                InvestmentsSummaryModel.date == date
            ).delete()
            self.session.commit()
        except Exception as e:
            logger.error(f"Error delete_summary {e}")
            self.session.rollback()

    def delete_all_holdings(self):
        """
        Delete all holdings (used in cleanup operations).
        """
        try:
            self.session.query(InvestmentsHoldingsModel).delete()
            self.session.commit()
        except Exception as e:
            logger.error(f"Error delete_all_holdings {e}")
            self.session.rollback()

    def delete_all_summary(self):
        """
        Delete all summary records (used in cleanup operations).
        """
        try:
            self.session.query(InvestmentsSummaryModel).delete()
            self.session.commit()
        except Exception as e:
            logger.error(f"Error deleting all summary {e}")
            self.session.rollback()