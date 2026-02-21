from db import db
from sqlalchemy import PrimaryKeyConstraint, Index


class MarketDataModel(db.Model):
    __tablename__ = "market_data"

    instrument_token = db.Column(db.Integer, nullable=False)
    tradingsymbol = db.Column(db.String, nullable=False)
    exchange = db.Column(db.String, nullable=False)
    date = db.Column(db.Date, nullable=False)

    open = db.Column(db.Float)
    high = db.Column(db.Float)
    low = db.Column(db.Float)
    close = db.Column(db.Float)
    volume = db.Column(db.Float)

    __table_args__ = (
        PrimaryKeyConstraint("instrument_token", "date"),
        Index("idx_marketdata_tradingsymbol_date", "tradingsymbol", "date"),
    )

    def __repr__(self):
        return f"<MarketData {self.tradingsymbol} {self.date}>"
