from db import db
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError

from models import HoldingsModel

class HoldingsRepository:
    
    @staticmethod
    def get_holdings(working_date=None):
        if not working_date:
            working_date = db.session.query(func.max(HoldingsModel.working_date)).scalar()

        return HoldingsModel.query.filter(HoldingsModel.working_date == working_date).all()


    @staticmethod
    def get_holdings_by_symbol(tradingsymbol, working_date=None):
        if not working_date:
            return HoldingsModel.query.filter(HoldingsModel.tradingsymbol == tradingsymbol).all()

        elif working_date == 'latest':
            working_date = db.session.query(func.max(HoldingsModel.working_date)).scalar()

        return HoldingsModel.query.filter(
            HoldingsModel.tradingsymbol == tradingsymbol,
            HoldingsModel.working_date == working_date
        ).all()


    @staticmethod
    def bulk_insert(holdings):
        try:
            db.session.bulk_insert_mappings(HoldingsModel, holdings, return_defaults=True)
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            return None
        return holdings
