"""
Investment Repository

Data access layer for holdings and portfolio summary.
Actions moved to repositories/actions_repository.py for better separation.
"""
from typing import Optional
from db import db
from sqlalchemy import func
from sqlalchemy.orm import Session
from models import (
    InvestmentsHoldingsModel,
    InvestmentsSummaryModel,
    CapitalEventModel,
)
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

    def get_all_summaries(self):
        """
        Get all summary records ordered by date ascending.
        
        Returns:
            list: InvestmentsSummaryModel instances
        """
        return self.session.query(InvestmentsSummaryModel).order_by(
            InvestmentsSummaryModel.date.asc()
        ).all()

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

    # ── Capital Events ──────────────────────────────────

    def get_all_capital_events(self):
        """
        Get all capital events ordered by date ascending.

        Returns:
            list: CapitalEventModel instances
        """
        return self.session.query(CapitalEventModel).order_by(
            CapitalEventModel.date.asc()
        ).all()

    def get_total_capital(self, target_date=None, include_realized=False):
        """
        Sum of all capital event amounts up to target_date.

        Parameters:
            target_date: Cut-off date (inclusive). None = all.
            include_realized: Whether to include 'realized_gain' events.

        Returns:
            float: Total capital infused/withdrawn
        """
        query = self.session.query(
            func.sum(CapitalEventModel.amount)
        )
        if not include_realized:
            query = query.filter(
                CapitalEventModel.event_type != 'realized_gain'
            )
            
        if target_date:
            query = query.filter(
                CapitalEventModel.date <= target_date
            )
        result = query.scalar()
        return float(result) if result else 0.0

    def insert_capital_event(self, event_dict):
        """
        Insert a capital event record.

        Parameters:
            event_dict (dict): Keys date, amount, event_type, note

        Returns:
            bool: True if successful, None otherwise
        """
        try:
            obj = CapitalEventModel(**event_dict)
            self.session.add(obj)
            self.session.commit()
            return True
        except Exception as e:
            logger.error(f"Error inserting capital event: {e}")
            self.session.rollback()
            return None

    def delete_capital_events(self, date=None, event_type=None):
        """
        Delete capital events by date and/or type.
        
        Parameters:
            date: Optional date to filter by
            event_type: Optional event type to filter by
        """
        try:
            query = self.session.query(CapitalEventModel)
            if date:
                query = query.filter(CapitalEventModel.date == date)
            if event_type:
                query = query.filter(CapitalEventModel.event_type == event_type)
            query.delete()
            self.session.commit()
        except Exception as e:
            logger.error(f"Error deleting capital events: {e}")
            self.session.rollback()

    def delete_all_capital_events(self):
        """
        Delete all capital events (used in cleanup).
        """
        try:
            self.session.query(CapitalEventModel).delete()
            self.session.commit()
        except Exception as e:
            logger.error(
                f"Error deleting all capital events: {e}"
            )
            self.session.rollback()