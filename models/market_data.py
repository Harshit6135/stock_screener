from sqlalchemy import ForeignKey, PrimaryKeyConstraint, Index
from db import db

class MarketDataModel(db.Model):
    __tablename__ = "market_data"

    instrument_token = db.Column(
        db.Integer,
        nullable=False
    )

    # denormalized for fast access
    ticker = db.Column(db.String, nullable=False)

    exchange = db.Column(db.String, nullable=False)
    date = db.Column(db.Date, nullable=False)

    open = db.Column(db.Float)
    high = db.Column(db.Float)
    low = db.Column(db.Float)
    close = db.Column(db.Float)
    volume = db.Column(db.Float)

    __table_args__ = (
        # ✅ composite primary key
        PrimaryKeyConstraint("instrument_token", "date"),

        # 🚀 fast lookup by ticker + date
        Index("idx_marketdata_ticker_date", "ticker", "date"),
    )

    def __repr__(self):
        return f"<MarketData {self.ticker} {self.date}>"
