from sqlalchemy import ForeignKey, PrimaryKeyConstraint, Index
from db import db

class IndicatorsModel(db.Model):
    __tablename__ = "indicators"

    instrument_id = db.Column(
        db.Integer,
        ForeignKey("instruments.instrument_token"),
        nullable=False
    )
    date = db.Column(db.Date, nullable=False)

    # denormalized for fast access
    ticker = db.Column(db.String, nullable=False)
    exchange = db.Column(db.String, nullable=False)

    rsi_14 = db.Column(db.Float)
    ema_50 = db.Column(db.Float)
    ema_200 = db.Column(db.Float)
    macd = db.Column(db.Float)

    __table_args__ = (
        # composite primary key
        PrimaryKeyConstraint("instrument_id", "date"),

        # fast lookup by ticker + date
        Index("idx_indicator_ticker_date", "ticker", "date"),
    )

    instrument = db.relationship(
        "InstrumentModel",
        backref=db.backref("indicators", lazy="dynamic")
    )

    def __repr__(self):
        return f"<Indicator {self.ticker} {self.date}>"
