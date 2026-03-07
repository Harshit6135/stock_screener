"""
Investment Models

Database models for holdings and portfolio summary.
Actions moved to models/actions.py for better separation.
"""
from db import db
from sqlalchemy import Index


class InvestmentsHoldingsModel(db.Model):
    """Investment holdings tracking current positions with price and stop-loss data"""
    __tablename__ = 'investment_holdings'
    __bind_key__ = 'personal'

    symbol = db.Column(db.String(50), primary_key=True, nullable=False)
    date = db.Column(db.Date, primary_key=True, nullable=False)
    entry_date = db.Column(db.Date, nullable=False)
    entry_price = db.Column(db.Numeric(10, 2), nullable=False)
    avg_price = db.Column(db.Numeric(10, 2), nullable=True)  # weighted avg cost for unrealized P&L
    units = db.Column(db.Integer, nullable=False)
    atr = db.Column(db.Numeric(10, 2), nullable=True)
    score = db.Column(db.Numeric(10, 2), nullable=True)
    entry_sl = db.Column(db.Numeric(10, 2), nullable=False)
    current_price = db.Column(db.Numeric(10, 2), nullable=False)
    current_sl = db.Column(db.Numeric(10, 2), nullable=False)

    __table_args__ = (
        Index("idx_investment_holdings_symbol", "symbol"),
        Index("idx_investment_holdings_date", "date"),
        Index("idx_investment_holdings_entry_date", "entry_date"),
    )

    @property
    def risk(self):
        """Calculate risk: (entry_price - current_sl) * units, minimum 0"""
        if self.entry_price and self.current_sl and self.units:
            risk_value = (float(self.entry_price) - float(self.current_sl)) * self.units
            return round(max(risk_value, 0), 2)
        return 0.0

    def __repr__(self):
        return f"<InvestmentsHolding {self.symbol} qty={self.units} @ {self.entry_price}>"

    def to_dict(self):
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}


class InvestmentsSummaryModel(db.Model):
    """Investment summary tracking weekly capital, risk, and portfolio metrics"""
    __tablename__ = 'investment_summary'
    __bind_key__ = 'personal'

    date = db.Column(db.Date, primary_key=True, nullable=False)
    starting_capital = db.Column(db.Numeric(12, 2), nullable=False)
    sold = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    bought = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    capital_risk = db.Column(db.Numeric(12, 2), nullable=True)
    portfolio_value = db.Column(db.Numeric(12, 2), nullable=False)
    portfolio_risk = db.Column(db.Numeric(12, 2), nullable=True)
    gain = db.Column(db.Numeric(12, 2), nullable=True)
    gain_percentage = db.Column(db.Numeric(12, 2), nullable=True)
    
    # Generated column - automatically calculated by database
    remaining_capital = db.Column(
        db.Numeric(12, 2),
        db.Computed('starting_capital + sold - bought'),
        nullable=True
    )

    __table_args__ = (
        Index("idx_investment_summary_date", "date"),
    )

    def __repr__(self):
        return f"<InvestmentsSummary {self.date} capital={self.starting_capital}>"

    def to_dict(self):
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}


class CapitalEventModel(db.Model):
    """Tracks capital infusions and withdrawals over time."""
    __tablename__ = 'capital_events'
    __bind_key__ = 'personal'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    date = db.Column(db.Date, nullable=False)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    event_type = db.Column(
        db.String(20), nullable=False
    )  # 'initial' | 'infusion' | 'withdrawal'
    note = db.Column(db.String(200), nullable=True)

    __table_args__ = (
        Index("idx_capital_events_date", "date"),
    )

    def __repr__(self):
        return (
            f"<CapitalEvent {self.event_type} "
            f"{self.amount} on {self.date}>"
        )

    def to_dict(self):
        return {
            c.name: getattr(self, c.name)
            for c in self.__table__.columns
        }


class BacktestRunModel(db.Model):
    """Stores metadata for each backtest run. Heavy data (summary, equity curve,
    trades, report) is stored as files on disk; only the folder path is kept here."""
    __tablename__ = 'backtest_runs'
    __bind_key__ = 'personal'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    run_label = db.Column(db.String(200), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False)
    config_name = db.Column(db.String(100), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    check_daily_sl = db.Column(db.Boolean, nullable=False, default=True)
    mid_week_buy = db.Column(db.Boolean, nullable=False, default=True)
    total_return = db.Column(db.Numeric(10, 2), nullable=True)
    max_drawdown = db.Column(db.Numeric(10, 2), nullable=True)
    sharpe_ratio = db.Column(db.Numeric(10, 2), nullable=True)
    data_dir = db.Column(db.String(500), nullable=False)

    def __repr__(self):
        return f"<BacktestRun {self.id} {self.run_label or ''} {self.start_date}->{self.end_date}>"

    def to_dict(self):
        return {
            'id': self.id,
            'run_label': self.run_label,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'config_name': self.config_name,
            'start_date': str(self.start_date),
            'end_date': str(self.end_date),
            'check_daily_sl': self.check_daily_sl,
            'mid_week_buy': self.mid_week_buy,
            'total_return': float(self.total_return) if self.total_return is not None else None,
            'max_drawdown': float(self.max_drawdown) if self.max_drawdown is not None else None,
            'sharpe_ratio': float(self.sharpe_ratio) if self.sharpe_ratio is not None else None,
            'data_dir': self.data_dir,
        }
