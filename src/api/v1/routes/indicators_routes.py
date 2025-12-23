from flask.views import MethodView
from flask_smorest import Blueprint, abort
from repositories import IndicatorsRepository

from schemas import IndicatorsSchema, MaxDateSchema
from services import IndicatorsService

blp = Blueprint("indicators", __name__, url_prefix="/api/v1/indicators", description="Operations on indicators")
indicators_repository = IndicatorsRepository()


@blp.route("/")
class Indicators(MethodView):
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
    @blp.arguments(IndicatorsSchema, location="json")
    @blp.response(200, IndicatorsSchema(many=True))
    def get(self, filter_data):
        """Fetch indicators by instrument_token or tradingsymbol within a date range"""
        return indicators_repository.query(filter_data)


@blp.route("/latest/<string:tradingsymbol>")
class LatestIndicatorsData(MethodView):
    @blp.response(200, IndicatorsSchema)
    def get(self, tradingsymbol):
        """Fetch the latest indicators for a tradingsymbol"""
        return indicators_repository.get_latest_date_by_symbol(tradingsymbol)


@blp.route("/max_date")
class IndicatorsMaxDate(MethodView):
    @blp.response(200, MaxDateSchema(many=True))
    def get(self):
        """Fetch the max date for each instrument"""
        return indicators_repository.get_latest_date_for_all()


@blp.route("/query/all")
class IndicatorsQueryAll(MethodView):
    @blp.arguments(IndicatorsSchema, location="json")
    @blp.response(200, IndicatorsSchema(many=True))
    def get(self, filter_data):
        """Fetch indicators by instrument_token or tradingsymbol within a date range"""
        response=indicators_repository.get_indicators_for_all_stocks(filter_data)
        indicators = {}
        for data in response:
            if data.tradingsymbol not in indicators:
                indicators[data.tradingsymbol] = []
            indicators[data.tradingsymbol].append(data)

        return indicators


@blp.route("/delete/<string:tradingsymbol>")
class IndicatorsDelete(MethodView):
    @blp.arguments(IndicatorsSchema, location="json")
    @blp.response(200, IndicatorsSchema(many=True))
    def delete(self, tradingsymbol):
        """Delete indicators by instrument_token or tradingsymbol within a date range"""
        response=indicators_repository.delete_by_tradingsymbol(tradingsymbol)
        if response == -1:
            abort(500, message="Failed to delete indicators")
        return response


@blp.route("/update_all")
class IndicatorsUpdateAll(MethodView):

    def post(self):
        """Calculate indicators for all instruments"""
        indicators_service = IndicatorsService()
        indicators_service.calculate_indicators()
        return "Calculation of Indicators completed."
