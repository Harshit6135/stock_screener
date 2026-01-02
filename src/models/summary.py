from db import db

class InvestmentSummary(db.Model):
    __tablename__ = 'investment_summary'
    __bind_key__ = 'personal'

    date = db.Column(db.Date, primary_key=True, nullable=False, index=True)
    sold = db.Column(db.Float, nullable=False)
    initial_capital = db.Column(db.Float, nullable=False)
    working_capital = db.Column(db.Float, nullable=False)
    bought = db.Column(db.Float, nullable=False)
    capital_risk = db.Column(db.Float, nullable=False)
    portfolio_value = db.Column(db.Float, nullable=False)
    portfolio_risk = db.Column(db.Float, nullable=False)
    remaining_capital = db.Column(db.Float, nullable=False)

    __table_args__ = (
        db.Index('idx_date', 'date'),
    )

    def __repr__(self):
        return f'<Summary {self.date}>'