from flask import jsonify, request
from flask_smorest import Blueprint, abort
from flask.views import MethodView
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import and_, or_

from db import db

from models import IndicatorsModel
from schemas import IndicatorsSchema

blp = Blueprint("indicators", __name__, description="Operations on indicators")

@blp.route("/indicators")
class Indicators(MethodView):
    @blp.arguments(IndicatorsSchema(many=True))
    @blp.response(201, IndicatorsSchema)
    def post(self, indicator_data):
        """Add an indicator entry"""
        try:
            db.session.bulk_insert_mappings(IndicatorsModel, indicator_data, return_defaults=True)
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            abort(500, message=str(e))
        return indicator_data

@blp.route("/indicators/query")
class IndicatorsQuery(MethodView):
    @blp.arguments(IndicatorsSchema, location="json")
    @blp.response(200, IndicatorsSchema(many=True))
    def get(self, filter_data):
        """Fetch indicators by instrument_token or ticker within a date range"""
        query = IndicatorsModel.query


@blp.route("/indicators/latest/<string:ticker>")
class LatestMarketData(MethodView):
    @blp.response(200, IndicatorsSchema)
    def get(self, ticker):
        """Fetch the latest market data for a ticker"""
        query = IndicatorsModel.query.filter(
            IndicatorsModel.ticker == ticker
        )

        return query.order_by(IndicatorsModel.date.desc()).first()
