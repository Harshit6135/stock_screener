from flask.views import MethodView
from flask_smorest import Blueprint, abort

from repositories import MarketDataRepository
from schemas import MarketDataSchema, MarketDataQuerySchema, MaxDateSchema
from services import MarketDataService

blp = Blueprint("marketdata", __name__, url_prefix="/api/v1/marketdata", description="Operations on market data")
marketdata_repo = MarketDataRepository()

@blp.route("/")
class MarketData(MethodView):
    @blp.arguments(MarketDataSchema(many=True))
    @blp.response(201, MarketDataSchema(many=True))
    def post(self, market_data):
        """Add multiple market data entries"""
        response = marketdata_repo.bulk_insert(market_data)
        if not response:
            abort(500, message="Failed pushing to database")
        return market_data


@blp.route("/query")
class MarketDataQuery(MethodView):
    @blp.arguments(MarketDataQuerySchema, location="json")
    @blp.response(200, MarketDataSchema(many=True))
    def get(self, filter_data):
        """Fetch market data by instrument_token or tradingsymbol within a date range"""
        return marketdata_repo.query(filter_data)


@blp.route("/max_date")
class MarketsDataMaxDate(MethodView):
    @blp.response(200, MaxDateSchema(many=True))
    def get(self):
        """Fetch the max date for each instrument"""
        return marketdata_repo.get_latest_date_for_all()


@blp.route("/latest/<string:tradingsymbol>")
class LatestMarketData(MethodView):
    @blp.response(200, MarketDataSchema)
    def get(self, tradingsymbol):
        """Fetch the latest market data for a tradingsymbol"""
        return marketdata_repo.get_latest_date_by_symbol(tradingsymbol)


@blp.route("/query/all")
class MarketDataQueryAll(MethodView):
    @blp.arguments(MarketDataQuerySchema, location="json")
    @blp.response(200, MarketDataSchema(many=True))
    def get(self, filter_data):
        """Fetch market data by instrument_token or tradingsymbol within a date range"""
        response=marketdata_repo.get_prices_for_all_stocks(filter_data)
        marketdata = {}
        for data in response:
            if data.tradingsymbol not in marketdata:
                marketdata[data.tradingsymbol] = []
            marketdata[data.tradingsymbol].append(data)

        return marketdata


@blp.route("/delete/<string:tradingsymbol>")
class MarketDataDelete(MethodView):
    @blp.arguments(MarketDataQuerySchema, location="json")
    @blp.response(200, MarketDataSchema(many=True))
    def delete(self, tradingsymbol):
        """Delete market data by instrument_token or tradingsymbol within a date range"""
        response=marketdata_repo.delete_by_tradingsymbol(tradingsymbol)
        if response == -1:
            abort(500, message="Failed to delete market data")
        return response


@blp.route("/update_all")
class MarketDataUpdateAll(MethodView):

    def post(self):
        """Fetch latest market data for all instruments"""
        marketdata_service = MarketDataService()
        marketdata_service.update_latest_data_for_all()
        return "Market data update completed."

@blp.route("/update_all/historical")
class MarketDataUpdateAllHistorical(MethodView):

    def post(self):
        """Fetch latest market data for all instruments"""
        marketdata_service = MarketDataService()
        marketdata_service.update_latest_data_for_all(historical=True)
        return "Market data update completed."
