from db import db
from sqlalchemy import Index


class ActionsModel(db.Model):
    """Recommended trade actions based on ranking and portfolio logic"""
    __tablename__ = "actions"

    id = db.Column(db.Integer, primary_key=True)
    action_date = db.Column(db.Date, nullable=False)
    action_type = db.Column(db.String(10), nullable=False)  # BUY, SELL, SWAP
    
    # Primary stock
    tradingsymbol = db.Column(db.String(50), nullable=False)
    units = db.Column(db.Integer, nullable=False)
    expected_price = db.Column(db.Float, nullable=True)
    amount = db.Column(db.Float, nullable=True)  # units × expected_price
    composite_score = db.Column(db.Float, nullable=True)
    
    # Buy range (don't buy if price outside this range)
    buy_price_min = db.Column(db.Float, nullable=True)  # Lower bound (e.g. -3% from expected)
    buy_price_max = db.Column(db.Float, nullable=True)  # Upper bound (e.g. +2% from expected)
    
    # For SWAP actions
    swap_from_symbol = db.Column(db.String(50), nullable=True)
    swap_from_units = db.Column(db.Integer, nullable=True)
    swap_from_price = db.Column(db.Float, nullable=True)
    
    # Tracking
    status = db.Column(db.String(20), default='PENDING')  # PENDING, INVESTED, SKIPPED, EXPIRED
    reason = db.Column(db.String(200), nullable=True)
    executed = db.Column(db.Boolean, default=False)
    executed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    __table_args__ = (
        Index("idx_actions_date", "action_date"),
        Index("idx_actions_type", "action_type"),
    )

    def __repr__(self):
        return f"<Action {self.action_type} {self.tradingsymbol} x{self.units}>"
