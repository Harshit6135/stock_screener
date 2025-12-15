from db import db
from sqlalchemy import and_, or_
from models import MarketDataModel
from flask.views import MethodView
from flask_smorest import Blueprint, abort
from sqlalchemy.exc import SQLAlchemyError
from schemas import MarketDataSchema, MarketDataQuerySchema, MaxDateSchema


blp = Blueprint("market_data", __name__, description="Operations on market data")

@blp.route("/market_data")
class MarketData(MethodView):
    @blp.arguments(MarketDataSchema(many=True))
    @blp.response(201, MarketDataSchema(many=True))
    def post(self, market_data):
        """Add multiple market data entries"""
        try:
            db.session.bulk_insert_mappings(MarketDataModel, market_data, return_defaults=True)
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            abort(500, message=str(e))
        return market_data

@blp.route("/market_data/query")
class MarketDataQuery(MethodView):
    @blp.arguments(MarketDataQuerySchema, location="json")
    @blp.response(200, MarketDataSchema(many=True))
    def get(self, filter_data):
        """Fetch market data by instrument_token or tradingsymbol within a date range"""
        query = MarketDataModel.query

        instrument_filter = []
        if "instrument_token" in filter_data:
            instrument_filter.append(MarketDataModel.instrument_token == filter_data["instrument_token"])
        if "tradingsymbol" in filter_data:
            instrument_filter.append(MarketDataModel.tradingsymbol == filter_data["tradingsymbol"])

        if instrument_filter:
            query = query.filter(or_(*instrument_filter))

        query = query.filter(
            and_(
                MarketDataModel.date >= filter_data["start_date"],
                MarketDataModel.date <= filter_data["end_date"],
            )
        )

        return query.all()

@blp.route("/market_data/max_date")
class MaxDate(MethodView):
    @blp.response(200, MaxDateSchema(many=True))
    def get(self):
        """Fetch the max date for each instrument"""
        query = db.session.query(
            MarketDataModel.instrument_token,
            MarketDataModel.tradingsymbol,
            func.max(MarketDataModel.date).label("max_date")
        ).group_by(MarketDataModel.instrument_token)

        return query.all()

@blp.route("/market_data/latest/<string:tradingsymbol>")
class LatestMarketData(MethodView):
    @blp.response(200, MarketDataSchema)
    def get(self, tradingsymbol):
        """Fetch the latest market data for a tradingsymbol"""
        query = MarketDataModel.query.filter(
            MarketDataModel.tradingsymbol == tradingsymbol
        )

        return query.order_by(MarketDataModel.date.desc()).first()
