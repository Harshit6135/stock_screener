from db import db
from sqlalchemy.exc import SQLAlchemyError

from models import InvestedModel


class PortfolioRepository:
    
    @staticmethod
    def get_invested():
        return InvestedModel.query.all()

    @staticmethod
    def get_invested_by_symbol(symbol):
        return InvestedModel.query.filter_by(tradingsymbol=symbol).first()

    @staticmethod
    def buy_stock(stock_data):
        try:
            investment = InvestedModel(**stock_data)
            db.session.add(investment)
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            return None
        return True

    @staticmethod
    def sell_stock(tradingsymbol):
        try:
            invested = InvestedModel.query.filter(tradingsymbol=tradingsymbol).first()
            if invested:
                db.session.delete(invested)
                db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            return None
        return True

    @staticmethod
    def delete_all():
        try:
            num_deleted = InvestedModel.query.delete()
            db.session.commit()
            return {"message": f"Deleted {num_deleted} positions"}
        except SQLAlchemyError as e:
            db.session.rollback()
            return None

    @staticmethod
    def delete_stock(symbol):
        invested = InvestedModel.query.filter_by(tradingsymbol=symbol).first()
        if not invested:
            return None
        try:
            db.session.delete(invested)
            db.session.commit()
            return {"message": f"Removed {symbol} from portfolio"}
        except SQLAlchemyError as e:
            db.session.rollback()
            return None

    @staticmethod
    def update_stock(invested_model):
        try:
            db.session.commit()
            return invested_model
        except SQLAlchemyError as e:
            db.session.rollback()
            return None
