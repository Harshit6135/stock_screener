from flask import request
from flask.views import MethodView
from flask_smorest import Blueprint, abort
from datetime import datetime
from repositories import IndicatorsRepository

from schemas import IndicatorsSchema, MaxDateSchema, IndicatorSearchSchema
from services import IndicatorsService


blp = Blueprint("Indicators", __name__, url_prefix="/api/v1/indicators", description="Operations on indicators")
indicators_repository = IndicatorsRepository()


@blp.route("/")
class Indicators(MethodView):
    @blp.doc(tags=["Indicators"])
    @blp.arguments(IndicatorsSchema(many=True))
    @blp.response(201, IndicatorsSchema)
    def post(self, indicator_data):
        """Add an indicator entry"""
        response = indicators_repository.bulk_insert(indicator_data)
        if response is None:
            abort(500, message="Failed to add indicators")
        return response


@blp.route("/query")
class IndicatorsQuery(MethodView):
    @blp.doc(tags=["Indicators"])
    @blp.arguments(IndicatorSearchSchema, location="json")
    @blp.response(200, IndicatorsSchema(many=True))
    def get(self, filter_data):
        """Fetch indicators by tradingsymbol within a date range"""
        return indicators_repository.query(filter_data)


@blp.route("/latest/<string:tradingsymbol>")
class LatestIndicatorsData(MethodView):
    @blp.doc(tags=["Indicators"])
    @blp.response(200, IndicatorsSchema)
    def get(self, tradingsymbol):
        """Fetch the latest indicators for a tradingsymbol"""
        return indicators_repository.get_latest_date_by_symbol(tradingsymbol)


@blp.route("/max_date")
class IndicatorsMaxDate(MethodView):
    @blp.doc(tags=["Indicators"])
    @blp.response(200, MaxDateSchema(many=True))
    def get(self):
        """Fetch the max date for each instrument"""
        return indicators_repository.get_latest_date_for_all()


@blp.route("/query/all")
class IndicatorsQueryAll(MethodView):
    @blp.doc(tags=["Indicators"])
    @blp.arguments(IndicatorsSchema, location="json")
    def get(self, filter_data):
        """Fetch indicators by tradingsymbol within a date range"""
        response=indicators_repository.get_indicators_for_all_stocks(filter_data)
        indicators = {}
        for data in response:
            if data.tradingsymbol not in indicators:
                indicators[data.tradingsymbol] = []
            indicators[data.tradingsymbol].append(data)

        return indicators


@blp.route("/delete/<string:tradingsymbol>")
class IndicatorsDelete(MethodView):
    @blp.doc(tags=["Indicators"])
    def delete(self, tradingsymbol):
        """Delete indicators by tradingsymbol"""
        response=indicators_repository.delete_by_tradingsymbol(tradingsymbol)
        if response == -1:
            abort(500, message="Failed to delete indicators")
        return response


@blp.route("/update_all")
class IndicatorsUpdateAll(MethodView):
    @blp.doc(tags=["Indicators"])
    def post(self):
        """Calculate indicators for all instruments"""
        indicators_service = IndicatorsService()
        indicators_service.calculate_indicators()
        return {"message": "Calculation of Indicators completed."}


@blp.route("/<string:indicator_name>")
class IndicatorByName(MethodView):
    @blp.doc(tags=["Indicators"])
    def get(self, indicator_name: str):
        """
        Get specific indicator value for a stock on a date.
        
        Used by backtesting API client.
        
        Parameters:
            indicator_name: Column name (e.g., 'atrr_14', 'ema_200')
            tradingsymbol: Query param - Stock symbol
            date: Query param - Date (YYYY-MM-DD)
            
        Returns:
            Dict with indicator name and value
        """
        tradingsymbol = request.args.get('tradingsymbol')
        date_str = request.args.get('date')
        
        if not tradingsymbol:
            abort(400, message="tradingsymbol query parameter required")
        
        as_of_date = None
        if date_str:
            try:
                as_of_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            except ValueError:
                abort(400, message="Invalid date format. Use YYYY-MM-DD")
        
        value = indicators_repository.get_indicator_by_tradingsymbol(
            indicator_name, tradingsymbol, as_of_date
        )
        
        return {indicator_name: value}
