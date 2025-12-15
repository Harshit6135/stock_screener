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
    market_cap = db.Column(db.Float, nullable=True)
    previous_close = db.Column(db.Float, nullable=True)
    all_time_high = db.Column(db.Float, nullable=True)
    all_time_low = db.Column(db.Float, nullable=True)
    shares_outstanding = db.Column(db.Float, nullable=True)
    float_shares = db.Column(db.Float, nullable=True)
    held_percent_insiders = db.Column(db.Float, nullable=True)
    held_percent_institutions = db.Column(db.Float, nullable=True)
    
    # Metadata
    status = db.Column(db.String, default='Active')
    
    def __repr__(self):
        return f"<MasterStock {self.isin} - {self.name_of_company}>"
