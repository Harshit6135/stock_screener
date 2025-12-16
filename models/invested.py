from db import db
from sqlalchemy import Index


class InvestedModel(db.Model):
    """Currently invested stocks with stop-loss tracking"""
    __tablename__ = "invested"

    id = db.Column(db.Integer, primary_key=True)
    tradingsymbol = db.Column(db.String(50), nullable=False, unique=True)
    instrument_token = db.Column(db.Integer, nullable=True)
    exchange = db.Column(db.String(10), nullable=True, default="NSE")
    
    # Position details
    buy_price = db.Column(db.Float, nullable=False)
    num_shares = db.Column(db.Integer, nullable=False)
    buy_date = db.Column(db.Date, nullable=False)
    
    # Stop-loss levels
    atr_at_entry = db.Column(db.Float, nullable=True)
    initial_stop_loss = db.Column(db.Float, nullable=False)
    current_stop_loss = db.Column(db.Float, nullable=False)
    
    # Tracking
    current_score = db.Column(db.Float, nullable=True)
    last_updated = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())
    
    # Strategy inclusion - if False, this position is managed manually
    include_in_strategy = db.Column(db.Boolean, nullable=False, default=True)
    
    __table_args__ = (
        Index("idx_invested_symbol", "tradingsymbol"),
    )

    def __repr__(self):
        return f"<Invested {self.tradingsymbol} qty={self.num_shares} @ {self.buy_price}>"
    
    @property
    def investment_value(self):
        return self.buy_price * self.num_shares
