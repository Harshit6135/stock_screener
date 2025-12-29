from db import db
from sqlalchemy import Index

class HoldingsModel(db.Model):
    __tablename__ = 'holdings'
    __bind_key__ = 'personal'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    tradingsymbol = db.Column(db.String(50), nullable=False, index=True)
    working_date = db.Column(db.Date, nullable=False, index=True)
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
