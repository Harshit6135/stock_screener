from db import db

class InstrumentModel(db.Model):
    __tablename__ = "instruments"

    instrument_token = db.Column(db.Integer, primary_key=True)
    exchange_token = db.Column(db.String, nullable=True)
    tradingsymbol = db.Column(db.String, nullable=True)
    name = db.Column(db.String, nullable=True)
    exchange = db.Column(db.String, nullable=True)

    def __repr__(self):
        return f"<Instrument {self.instrument_token} - {self.tradingsymbol}>"
