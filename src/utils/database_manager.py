"""
Database Manager

Utility for managing multiple database sessions (main, personal, backtest).
"""
from typing import Optional
from sqlalchemy.orm import scoped_session, sessionmaker

from db import db
from config import setup_logger

logger = setup_logger(name="DatabaseManager")


class DatabaseManager:
    """
    Manage database sessions for different binds.
    
    Binds:
        - None (default): main database (market_data.db)
        - 'personal': real investment data (personal.db)
        - 'backtest': simulated investment data (backtest.db)
    """
    
    _sessions = {}
    
    @classmethod
    def get_session(cls, bind_key: Optional[str] = None):
        """
        Get session for specific database bind.
        
        Parameters:
            bind_key: Database bind key ('personal', 'backtest', or None for main)
            
        Returns:
            SQLAlchemy session for the specified bind
        """
        if bind_key is None:
            return db.session
        
        if bind_key not in cls._sessions:
            engine = db.get_engine(bind=bind_key)
            session_factory = sessionmaker(bind=engine)
            cls._sessions[bind_key] = scoped_session(session_factory)
        
        return cls._sessions[bind_key]
    
    @classmethod
    def get_backtest_session(cls):
        """Convenience method to get backtest session."""
        return cls.get_session('backtest')
    
    @classmethod
    def init_backtest_db(cls, app):
        """
        Initialize backtest database with required tables.
        
        Creates investment_actions, investment_holdings, investment_summary tables.
        """
        from src.models.investment import (
            InvestmentActionsModel,
            InvestmentHoldingsModel, 
            InvestmentSummaryModel
        )
        
        with app.app_context():
            engine = db.get_engine(bind='backtest')
            
            # Create tables if they don't exist
            InvestmentActionsModel.__table__.create(engine, checkfirst=True)
            InvestmentHoldingsModel.__table__.create(engine, checkfirst=True)
            InvestmentSummaryModel.__table__.create(engine, checkfirst=True)
            
            logger.info("Backtest database initialized")
    
    @classmethod
    def clear_backtest_db(cls, app):
        """
        Clear all data from backtest database.
        
        Call before starting a new backtest run.
        """
        session = cls.get_backtest_session()
        
        with app.app_context():
            from src.models.investment import (
                InvestmentActionsModel,
                InvestmentHoldingsModel,
                InvestmentSummaryModel
            )
            
            try:
                session.query(InvestmentActionsModel).delete()
                session.query(InvestmentHoldingsModel).delete()
                session.query(InvestmentSummaryModel).delete()
                session.commit()
                logger.info("Backtest database cleared")
            except Exception as e:
                session.rollback()
                logger.error(f"Error clearing backtest DB: {e}")
    
    @classmethod
    def close_sessions(cls):
        """Close all custom sessions."""
        for session in cls._sessions.values():
            session.remove()
        cls._sessions.clear()
