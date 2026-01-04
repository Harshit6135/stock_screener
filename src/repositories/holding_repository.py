from db import db
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError

from models import HoldingsModel, SummaryModel

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
        if holdings:
            HoldingsRepository.delete_holdings_by_date(holdings[0]['working_date'])
        try:
            db.session.bulk_insert_mappings(HoldingsModel, holdings, return_defaults=True)
            db.session.commit()
        except SQLAlchemyError as e:
            print(e)
            db.session.rollback()
            return None
        return holdings

    @staticmethod
    def delete_holdings_by_date(working_date):
        try:
            HoldingsModel.query.filter(HoldingsModel.working_date == working_date).delete()
            db.session.commit()
        except SQLAlchemyError as e:
            print(e)
            db.session.rollback()
            return None


    @staticmethod
    def insert_summary(summary):
        summary_data = SummaryModel(**summary)
        try:
            SummaryModel.query.filter(SummaryModel.working_date == summary_data.working_date).delete()
            db.session.commit()
        except SQLAlchemyError as e:
            print(e)
            db.session.rollback()

        try:
            db.session.add(summary_data)
            db.session.commit()
        except SQLAlchemyError as e:
            print(e)
            db.session.rollback()
            return None
        return summary_data


    @staticmethod
    def get_summary(working_date=None):
        if not working_date:
            working_date = db.session.query(func.max(SummaryModel.working_date)).scalar()

        return SummaryModel.query.filter(SummaryModel.working_date == working_date).first()

    @staticmethod
    def delete_holdings_all():
        try:
            HoldingsModel.query.delete()
            db.session.commit()
        except SQLAlchemyError as e:
            print(e)
            db.session.rollback()
            return None
        return None


    @staticmethod
    def delete_summary_all():
        try:
            SummaryModel.query.delete()
            db.session.commit()
        except SQLAlchemyError as e:
            print(e)
            db.session.rollback()
            return None
        return None