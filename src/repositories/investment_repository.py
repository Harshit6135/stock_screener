from db import db
from sqlalchemy import func
from models import InvestmentActionsModel, InvestmentHoldingsModel, InvestmentSummaryModel


class InvestmentRepository:

    @staticmethod
    def get_actions(working_date=None):
        if not working_date:
            working_date = db.session.query(func.max(InvestmentActionsModel.working_date)).scalar()
        return InvestmentActionsModel.query.filter(InvestmentActionsModel.working_date == working_date).all()


    @staticmethod
    def get_holdings(working_date=None):
        if not working_date:
            working_date = db.session.query(func.max(InvestmentHoldingsModel.working_date)).scalar()
        return InvestmentHoldingsModel.query.filter(InvestmentHoldingsModel.working_date == working_date).all()


    @staticmethod
    def get_summary(working_date=None):
        if not working_date:
            working_date = db.session.query(func.max(InvestmentSummaryModel.working_date)).scalar()
        return InvestmentSummaryModel.query.filter(InvestmentSummaryModel.working_date == working_date).first()


    @staticmethod
    def bulk_insert_actions(actions):
        try:
            InvestmentActionsModel.query.filter(InvestmentActionsModel.working_date == actions[0]['working_date']).delete()
            db.session.commit()
        except Exception as e:
            print(f"Error bulk_insert_actions (delete) {e}")
            db.session.rollback()

        try:
            db.session.bulk_insert_mappings(InvestmentActionsModel, actions, return_defaults=True)
            db.session.commit()
        except Exception as e:
            print(f"Error bulk_insert_actions {e}")
            db.session.rollback()
            return None
        return True


    @staticmethod
    def bulk_insert_holdings(holdings):
        try:
            InvestmentHoldingsModel.query.filter(InvestmentHoldingsModel.working_date == holdings[0]['working_date']).delete()
            db.session.commit()
        except Exception as e:
            print(f"Error bulk_insert_actions (delete) {e}")
            db.session.rollback()

        try:
            db.session.bulk_insert_mappings(InvestmentHoldingsModel, holdings, return_defaults=True)
            db.session.commit()
        except Exception as e:
            print(f"Error bulk_insert_actions {e}")
            db.session.rollback()
            return None
        return True


    @staticmethod
    def insert_summary(summary):
        summary_data = InvestmentSummaryModel(**summary)
        try:
            InvestmentSummaryModel.query.filter(InvestmentSummaryModel.working_date == summary['working_date']).delete()
            db.session.commit()
        except Exception as e:
            print(f"Error as {e}")
            db.session.rollback()

        try:
            db.session.add(summary_data)
            db.session.commit()
            return True
        except Exception as e:
            print(f"Error as {e}")
            db.session.rollback()
            return None
