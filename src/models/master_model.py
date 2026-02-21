from db import db

class MasterModel(db.Model):
    __tablename__ = "master_stocks"

    isin = db.Column(db.String, primary_key=True)
    nse_symbol = db.Column(db.String, nullable=True)
    bse_symbol = db.Column(db.String, nullable=True)
    bse_security_code = db.Column(db.String, nullable=True)
    name_of_company = db.Column(db.String, nullable=True)
    
    # yfinance data
    industry = db.Column(db.String, nullable=True)
    sector = db.Column(db.String, nullable=True)
    marketcap = db.Column(db.Float, nullable=True)
    regularmarketprice = db.Column(db.Float, nullable=True)
    alltimehigh = db.Column(db.Float, nullable=True)
    alltimelow = db.Column(db.Float, nullable=True)
    sharesoutstanding = db.Column(db.Float, nullable=True)
    floatshares = db.Column(db.Float, nullable=True)
    heldpercentinsiders = db.Column(db.Float, nullable=True)
    heldpercentinstitutions = db.Column(db.Float, nullable=True)
    
    # Metadata
    status = db.Column(db.String, default='Active')
    
    def __repr__(self):
        return f"<MasterStock {self.isin} - {self.name_of_company}>"
