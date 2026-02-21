"""
Investment Routes

API endpoints for investment holdings, summary, and manual trades.
"""
from datetime import datetime
from flask.views import MethodView
from flask_smorest import Blueprint, abort
import marshmallow as ma
from typing import List

from config import setup_logger
from schemas import (
    ActionQuerySchema, HoldingDateSchema, HoldingSchema, SummarySchema, MessageSchema
)
from repositories import InvestmentRepository, ActionsRepository
from services import ActionsService

logger = setup_logger(name="InvestmentRoutes")
inv_repo = InvestmentRepository()
actions_repo = ActionsRepository()


blp = Blueprint(
    "Investments",
    __name__,
    url_prefix="/api/v1/investment",
    description="Investment Operations"
)


# --- Schema for manual trade input ---
class ManualBuySchema(ma.Schema):
    symbol = ma.fields.String(required=True, metadata={"description": "Trading symbol"})
    date = ma.fields.Date(required=True, metadata={"description": "Action date (YYYY-MM-DD)"})
    reason = ma.fields.String(load_default="Manual buy", metadata={"description": "Reason for trade"})
    config_name = ma.fields.String(load_default="momentum_config", metadata={"description": "Config name for config"})
    units = ma.fields.Integer(required=True, metadata={"description": "Number of units to buy"})
    price = ma.fields.Decimal(required=True, metadata={"description": "Price of the stock"})


class ManualSellSchema(ma.Schema):
    symbol = ma.fields.String(required=True, metadata={"description": "Trading symbol"})
    date = ma.fields.Date(required=True, metadata={"description": "Action date (YYYY-MM-DD)"})
    units = ma.fields.Integer(required=True, metadata={"description": "Number of units to sell"})
    reason = ma.fields.String(load_default="Manual sell", metadata={"description": "Reason for trade"})
    price = ma.fields.Float(required=True, metadata={"description": "Price of the stock"})



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
        """Get summary for a specific date"""
        working_date = args.get('date')
        summary = inv_repo.get_summary(working_date)
        if summary:
            return summary.to_dict()
        return {}


@blp.route("/manual/buy")
class ManualBuy(MethodView):
    @blp.doc(tags=["Investments"])
    @blp.arguments(ManualBuySchema(many=True))
    @blp.response(201, MessageSchema)
    def post(self, data):
        """
        Manually create a BUY action with position sizing.
        
        Generates a buy action using ATR-based position sizing,
        then inserts it into the actions table for approval.
        
        Parameters:
            symbol: Trading symbol
            date: Action date
            reason: Trade reason
            config_name: Config to use
        """
        try:
            actions = []
            for stock in data:
                service = ActionsService(stock['config_name'])
                action = service.buy_action(
                    symbol=stock['symbol'],
                    action_date=stock['date'],
                    prev_close=float(stock['price']),
                    reason=stock['reason'],
                    units=stock['units']
                )
                action['execution_price'] = float(stock['price'])
                actions.append(action)
            actions_repo.delete_actions(data[0]['date'])
            actions_repo.bulk_insert_actions(actions)
            return {"message": f"Manual BUY actions created for {[stock['symbol'] for stock in data]}"}
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
        """
        Manually create a SELL action.
        
        Generates a sell action for the specified symbol and units,
        then inserts it into the actions table for approval.
        
        Parameters:
            symbol: Trading symbol
            date: Action date
            units: Number of units to sell
            reason: Trade reason
        """
        try:
            action = ActionsService.sell_action(
                data['symbol'], data['date'], float(data['price']), data['units'], data['reason']
            )
            action['execution_price'] = float(data['price'])
            actions_repo.delete_actions(data['date'])
            actions_repo.bulk_insert_actions([action])
            return {"message": f"Manual SELL action created for {data['symbol']}: {data['units']} units"}
        except ValueError as e:
            logger.error(f"Validation error: {e}")
            abort(400, message=str(e))
        except Exception as e:
            logger.error(f"Failed to create manual sell: {e}")
            abort(500, message=f"Manual sell failed: {str(e)}")
