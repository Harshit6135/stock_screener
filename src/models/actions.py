from db import db
from sqlalchemy import Index


class ActionsModel(db.Model):
    """Recommended trade actions based on ranking and portfolio logic"""
    __tablename__ = "actions"
    __bind_key__ = "personal"

    action_date = db.Column(db.Date, primary_key=True, nullable=False)
    action_type = db.Column(db.String(10), nullable=False)  # BUY, SELL

    tradingsymbol = db.Column(db.String(50), primary_key=True, nullable=False)
    units = db.Column(db.Integer, nullable=False)
    price = db.Column(db.Float, nullable=False)
    composite_score = db.Column(db.Float, nullable=True)
    reason = db.Column(db.String(200), nullable=True)

    __table_args__ = (
        Index("idx_actions_date", "action_date"),
        Index("idx_actions_type", "action_type"),
    )

    def __repr__(self):
        return f"<Action {self.action_type} {self.tradingsymbol} x{self.units}>"
