from db import db
from sqlalchemy import Index

class HoldingsModel(db.Model):
    __tablename__ = 'holdings'
    __bind_key__ = 'personal'

    tradingsymbol = db.Column(db.String(50), primary_key=True, nullable=False, index=True)
    working_date = db.Column(db.Date, primary_key=True, nullable=False, index=True)
    entry_date = db.Column(db.Date, nullable=False)
    entry_price = db.Column(db.Float, nullable=False)
    score = db.Column(db.Float, nullable=False)
    atr = db.Column(db.Float, nullable=False)
    entry_sl = db.Column(db.Float, nullable=False)
    units = db.Column(db.Integer, nullable=False)
    risk = db.Column(db.Float, nullable=False)
    capital_needed = db.Column(db.Float, nullable=False)
    working_capital = db.Column(db.Float, nullable=False)
    current_price = db.Column(db.Float, nullable=False)
    current_sl = db.Column(db.Float, nullable=False)

    __table_args__ = (
        db.Index('idx_date_symbol', 'working_date', 'tradingsymbol'),
    )

    def __repr__(self):
        return f'<Trade {self.tradingsymbol} on {self.working_date}>'

    def to_dict(self):
        return { c.name: getattr(self, c.name) for c in self.__table__.columns}


class SummaryModel(db.Model):
    __tablename__ = 'summary'
    __bind_key__ = 'personal'

    working_date = db.Column(db.Date, primary_key=True, nullable=False)
    starting_capital = db.Column(db.Float, nullable=False)
    sold = db.Column(db.Float, nullable=False)
    working_capital = db.Column(db.Float, nullable=False)
    bought = db.Column(db.Float, nullable=False)
    capital_risk = db.Column(db.Float, nullable=False)
    portfolio_value = db.Column(db.Float, nullable=False)
    remaining_capital = db.Column(db.Float, nullable=False)
    portfolio_risk = db.Column(db.Float, nullable=False)

    __table_args__ = (
        db.Index('idx_date', 'working_date'),
    )

    def __repr__(self):
        return f'<Summary {self.working_date}>'
