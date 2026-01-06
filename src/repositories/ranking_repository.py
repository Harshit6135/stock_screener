from db import db
from sqlalchemy.exc import SQLAlchemyError

from config import setup_logger
from models import RankingModel

logger = setup_logger(name="RankingRepository")


class RankingRepository:
    
    @staticmethod
    def bulk_insert(ranking_records):
        try:
            db.session.bulk_insert_mappings(RankingModel, ranking_records, return_defaults=True)
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            logger.error(f"Error inserting Items to Table {e}")
            return None
        return ranking_records

    @staticmethod
    def delete(ranking_date):
        try:
            db.session.query(RankingModel).filter(RankingModel.ranking_date == ranking_date).delete()
            db.session.commit()
        except SQLAlchemyError as e:
            logger.error(f"Error deleting Items to Table {e}")
            db.session.rollback()
            return None
        return True

    @staticmethod
    def get_max_ranking_date():
        latest_record = RankingModel.query.order_by(RankingModel.ranking_date.desc()).first()
        return latest_record.ranking_date if latest_record else None

    @staticmethod
    def get_top_n_by_date(n, date=None):
        if date is None:
            latest = db.session.query(db.func.max(RankingModel.ranking_date)).scalar()
            if not latest:
                return []
        else:
            latest = date
        rankings = RankingModel.query.filter(
            RankingModel.ranking_date == latest
        ).order_by(
            RankingModel.composite_score.desc()
        ).limit(n).all()

        return rankings

    @staticmethod
    def get_rankings_by_date(ranking_date):
        return RankingModel.query.filter(
            RankingModel.ranking_date == ranking_date
        ).all()

    @staticmethod
    def get_latest_rank_by_symbol(symbol):
        """Get the latest available ranking record for a symbol"""
        return RankingModel.query.filter(
            RankingModel.tradingsymbol == symbol
        ).order_by(RankingModel.ranking_date.desc()).first()

    @staticmethod
    def get_rankings_by_date_and_symbol(ranking_date, symbol):
        return RankingModel.query.filter(
            RankingModel.ranking_date == ranking_date,
            RankingModel.tradingsymbol == symbol
        ).order_by(RankingModel.composite_score.desc()).all()