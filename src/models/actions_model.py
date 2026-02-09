"""
Actions Model

Database model for trading actions (BUY/SELL/SWAP).
Separated from investment module for clarity.
"""
from db import db
from sqlalchemy import Index
import uuid


class ActionsModel(db.Model):
    """Trading actions for buy/sell decisions with risk and ATR data"""
    __tablename__ = 'actions'
    __bind_key__ = 'personal'

    action_id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    action_date = db.Column(db.Date, nullable=False)
    type = db.Column(db.String(10), nullable=False)  # 'buy' or 'sell'
    reason = db.Column(db.String(50), nullable=True)
    symbol = db.Column(db.String(50), nullable=False)
    risk = db.Column(db.Numeric(10, 2), nullable=True)
    atr = db.Column(db.Numeric(10, 2), nullable=True)
    units = db.Column(db.Integer, nullable=False)
    prev_close = db.Column(db.Numeric(10,2), nullable=False)
    execution_price = db.Column(db.Numeric(10,2), nullable=True)
    capital = db.Column(db.Numeric(10,2), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='Pending')

    __table_args__ = (
        Index("idx_actions_action_date", "action_date"),
        Index("idx_actions_symbol", "symbol"),
        Index("idx_actions_status", "status"),
    )

    def __repr__(self):
        return f"<Action {self.action_id} {self.type} {self.symbol} x{self.units}>"

    def to_dict(self):
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}
