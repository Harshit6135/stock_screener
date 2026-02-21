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
