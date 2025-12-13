from db import db

class InstrumentModel(db.Model):
    __tablename__ = "instruments"

    instrument_token = db.Column(db.Integer, primary_key=True)
    exchange_token = db.Column(db.String, nullable=True)
    tradingsymbol = db.Column(db.String, nullable=True)
    name = db.Column(db.String, nullable=True)
    last_price = db.Column(db.Float, nullable=True)
    expiry = db.Column(db.String, nullable=True)
    strike = db.Column(db.Float, nullable=True)
    tick_size = db.Column(db.Float, nullable=True)
    lot_size = db.Column(db.Integer, nullable=True)
    instrument_type = db.Column(db.String, nullable=True)
    segment = db.Column(db.String, nullable=True)
    exchange = db.Column(db.String, nullable=True)

    def __repr__(self):
        return f"<Instrument {self.instrument_token} - {self.tradingsymbol}>"