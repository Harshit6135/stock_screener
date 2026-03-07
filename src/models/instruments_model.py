from db import db

class InstrumentsModel(db.Model):
    __tablename__ = "instruments"

    instrument_token = db.Column(db.Integer, primary_key=True)
    exchange_token = db.Column(db.String, nullable=True)
    tradingsymbol = db.Column(db.String, nullable=True)
    name = db.Column(db.String, nullable=True)
    exchange = db.Column(db.String, nullable=True)
    series = db.Column(db.String(10), nullable=True)  # e.g. 'EQ', 'BE'
    market_cap = db.Column(db.Float, nullable=True)
    industry = db.Column(db.String, nullable=True)
    sector = db.Column(db.String, nullable=True)

    def __repr__(self):
        return f"<Instrument {self.instrument_token} - {self.tradingsymbol}>"
