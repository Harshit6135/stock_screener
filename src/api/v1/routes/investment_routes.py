"""
Investment Routes

API endpoints for investment holdings, summary, and manual trades.
Thin controller layer — business logic lives in InvestmentService.
"""
from flask.views import MethodView
from flask_smorest import Blueprint, abort
import marshmallow as ma

from config import setup_logger
from schemas import (
    ActionQuerySchema, HoldingDateSchema, HoldingSchema, SummarySchema, MessageSchema,
ManualBuySchema, ManualSellSchema, CapitalEventSchema
)
from repositories import InvestmentRepository
from services import InvestmentService


logger = setup_logger(name="InvestmentRoutes")
inv_repo = InvestmentRepository()
inv_service = InvestmentService()


blp = Blueprint(
    "Investments",
    __name__,
    url_prefix="/api/v1/investment",
    description="Investment Operations"
)


@blp.route("/holdings/dates")
class HoldingDates(MethodView):
    @blp.doc(tags=["Investments"])
    @blp.response(200, HoldingDateSchema)
    def get(self):
        """Get all distinct holding dates"""
        dates = inv_repo.get_holdings_dates()
        return {"dates": dates}


@blp.route("/holdings")
class Holdings(MethodView):
    @blp.doc(tags=["Investments"])
    @blp.arguments(ActionQuerySchema, location="query")
    @blp.response(200, HoldingSchema(many=True))
    def get(self, args):
        """Get holdings for a specific date"""
        working_date = args.get('date')
        holdings = inv_repo.get_holdings(working_date)
        return [h.to_dict() for h in holdings]


@blp.route("/summary")
class Summary(MethodView):
    @blp.doc(tags=["Investments"])
    @blp.arguments(ActionQuerySchema, location="query")
    @blp.response(200, SummarySchema)
    def get(self, args):
        """Get summary for a specific date with live recalculation"""
        result = inv_service.get_portfolio_summary(args.get('date'))
        return result if result else {}


@blp.route("/manual/buy")
class ManualBuy(MethodView):
    @blp.doc(tags=["Investments"])
    @blp.arguments(ManualBuySchema(many=True))
    @blp.response(201, MessageSchema)
    def post(self, data):
        """Manually create BUY actions with position sizing"""
        try:
            message = inv_service.create_manual_buy(data)
            return {"message": message}
        except ValueError as e:
            logger.error(f"Validation error: {e}")
            abort(400, message=str(e))
        except Exception as e:
            logger.error(f"Failed to create manual buy: {e}")
            abort(500, message=f"Manual buy failed: {str(e)}")


@blp.route("/manual/sell")
class ManualSell(MethodView):
    @blp.doc(tags=["Investments"])
    @blp.arguments(ManualSellSchema)
    @blp.response(201, MessageSchema)
    def post(self, data):
        """Manually create a SELL action"""
        try:
            message = inv_service.create_manual_sell(data)
            return {"message": message}
        except ValueError as e:
            logger.error(f"Validation error: {e}")
            abort(400, message=str(e))
        except Exception as e:
            logger.error(f"Failed to create manual sell: {e}")
            abort(500, message=f"Manual sell failed: {str(e)}")


@blp.route("/sync-prices")
class SyncPrices(MethodView):
    @blp.doc(tags=["Investments"])
    @blp.response(200, MessageSchema)
    def post(self):
        """Sync portfolio holdings with latest market prices"""
        try:
            message = inv_service.sync_prices()
            return {"message": message}
        except Exception as e:
            logger.error(f"Failed to sync prices: {e}")
            abort(500, message=f"Sync failed: {str(e)}")


@blp.route("/summary/history")
class SummaryHistory(MethodView):
    @blp.doc(tags=["Investments"])
    @blp.response(200, SummarySchema(many=True))
    def get(self):
        """Get all historical summaries for equity curve and drawdown chart"""
        return inv_service.get_summary_history()


@blp.route("/trade-journal")
class TradeJournal(MethodView):
    @blp.doc(tags=["Investments"])
    def get(self):
        """Get trade journal — matched buy/sell pairs with P&L"""
        try:
            return inv_service.get_trade_journal()
        except Exception as e:
            logger.error(f"Failed to build trade journal: {e}")
            abort(500, message=f"Trade journal failed: {str(e)}")


@blp.route("/summary/recalculate")
class RecalculateSummary(MethodView):
    @blp.doc(tags=["Investments"])
    @blp.response(200, MessageSchema)
    def post(self):
        """Recalculate and fix all summary records in the DB"""
        try:
            message = inv_service.recalculate_summary()
            return {"message": message}
        except Exception as e:
            logger.error(f"Failed to recalculate summary: {e}")
            abort(500, message=f"Recalculate failed: {str(e)}")


@blp.route("/capital-events")
class CapitalEvents(MethodView):
    @blp.doc(tags=["Investments"])
    @blp.response(200, CapitalEventSchema(many=True))
    def get(self):
        """List all capital events"""
        return inv_service.get_capital_events()

    @blp.doc(tags=["Investments"])
    @blp.arguments(CapitalEventSchema)
    @blp.response(201, MessageSchema)
    def post(self, data):
        """Record a capital infusion or withdrawal"""
        try:
            message = inv_service.add_capital_event(
                event_date=data['date'],
                amount=data['amount'],
                event_type=data['event_type'],
                note=data.get('note', ''),
            )
            return {"message": message}
        except ValueError as e:
            logger.error(f"Validation error: {e}")
            abort(400, message=str(e))
        except Exception as e:
            logger.error(
                f"Failed to add capital event: {e}"
            )
            abort(
                500,
                message=f"Capital event failed: {str(e)}"
            )
