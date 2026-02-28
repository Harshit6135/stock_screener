from flask.views import MethodView
from flask_smorest import Blueprint, abort

from services import InitService
from schemas import InitResponseSchema, InitRequestSchema


blp = Blueprint("Initialization", __name__, url_prefix="/api/v1/init", description="Initialize App")


@blp.route("/")
class Init(MethodView):
    @blp.doc(tags=["Initialization"])
    @blp.arguments(InitRequestSchema, location="json", as_kwargs=True)
    @blp.response(201, InitResponseSchema)
    def post(self, **kwargs):
        """Initialize App"""
        batch_size = kwargs.get("yfinance_batch_size", 100)
        sleep_time = kwargs.get("yfinance_sleep_time", 4)
        try:
            init_service = InitService()
            response_code, response = init_service.initialize_app(batch_size=batch_size, sleep_time=sleep_time)
            if response_code not in [200, 201]:
                abort(response_code, message="Initialization failed during Kite sync")
        except Exception as e:
            abort(500, message=str(e))
        return response


@blp.route("/sync")
class InstrumentSync(MethodView):
    @blp.doc(tags=["Initialization"])
    def post(self):
        """
        Sync instrument tokens.

        Reads the existing instruments table, fetches the latest Kite instruments CSV,
        detects any series changes (EQ ↔ BE) for tracked symbols, and cascades the
        new instrument_token + exchange_token into market_data and indicators.
        Only changed symbols are touched — no data is deleted or re-inserted.

        Returns: { checked: N, changed: M, errors: K }
        """
        try:
            init_service = InitService()
            result = init_service.sync_instruments()
        except Exception as e:
            abort(500, message=str(e))
        return result, 200
