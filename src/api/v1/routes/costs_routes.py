"""
Costs Routes

API endpoints for transaction cost calculations.
Uses TransactionCostConfig - no hardcoded values.
"""
from flask import request
from flask.views import MethodView
from flask_smorest import Blueprint, abort

from src.utils.transaction_costs_utils import (
    calculate_round_trip_cost,
    calculate_buy_costs,
    calculate_sell_costs
)


blp = Blueprint(
    "costs", 
    __name__, 
    url_prefix="/api/v1/costs", 
    description="Transaction Cost Calculations"
)


@blp.route("/roundtrip")
class RoundTripCosts(MethodView):
    @blp.doc(tags=["Analysis"])
    def get(self):
        """
        Calculate round-trip transaction costs.
        
        Used by backtesting API client.
        
        Parameters:
            trade_value: Query param - Order value in INR
            order_pct_adv: Query param - Order as % of ADV (default: 0.05)
            
        Returns:
            Dict with buy_costs, sell_costs, impact_cost, total, percent
        """
        trade_value_str = request.args.get('trade_value')
        order_pct_adv_str = request.args.get('order_pct_adv', '0.05')
        
        if not trade_value_str:
            abort(400, message="trade_value query parameter required")
        
        try:
            trade_value = float(trade_value_str)
            order_pct_adv = float(order_pct_adv_str)
        except ValueError:
            abort(400, message="Invalid numeric value")
        
        result = calculate_round_trip_cost(trade_value, order_pct_adv)
        
        return result


@blp.route("/buy")
class BuyCosts(MethodView):
    @blp.doc(tags=["Analysis"])
    def get(self):
        """
        Calculate buy-side transaction costs only.
        
        Parameters:
            trade_value: Query param - Order value in INR
            
        Returns:
            Dict with cost breakdown
        """
        trade_value_str = request.args.get('trade_value')
        
        if not trade_value_str:
            abort(400, message="trade_value query parameter required")
        
        try:
            trade_value = float(trade_value_str)
        except ValueError:
            abort(400, message="Invalid numeric value")
        
        result = calculate_buy_costs(trade_value)
        
        return {"buy_costs": result}


@blp.route("/sell")
class SellCosts(MethodView):
    @blp.doc(tags=["Analysis"])
    def get(self):
        """
        Calculate sell-side transaction costs only.
        
        Parameters:
            trade_value: Query param - Order value in INR
            
        Returns:
            Dict with cost breakdown
        """
        trade_value_str = request.args.get('trade_value')
        
        if not trade_value_str:
            abort(400, message="trade_value query parameter required")
        
        try:
            trade_value = float(trade_value_str)
        except ValueError:
            abort(400, message="Invalid numeric value")
        
        result = calculate_sell_costs(trade_value)
        
        return {"sell_costs": result}
