"""
Costs Routes

API endpoints for transaction cost and position sizing calculations.
Uses TransactionCostConfig and PositionSizingConfig - no hardcoded values.
"""
from flask import request
from flask.views import MethodView
from flask_smorest import Blueprint, abort

from utils import (
    calculate_round_trip_cost,
    calculate_buy_costs,
    calculate_sell_costs
)
from src.utils.sizing_utils import (
    calculate_position_size,
    calculate_equal_weight_position
)


blp = Blueprint(
    "costs", 
    __name__, 
    url_prefix="/api/v1/costs", 
    description="Transaction Cost and Sizing Calculations"
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


@blp.route("/position-size")
class PositionSize(MethodView):
    @blp.doc(tags=["Analysis"])
    def get(self):
        """
        Calculate ATR-based position size with multiple constraints.
        
        Parameters:
            atr: Query param - Average True Range
            current_price: Query param - Current stock price
            portfolio_value: Query param - Total portfolio value
            avg_daily_volume_value: Query param (optional) - 20-day ADV in INR
            
        Returns:
            Dict with shares, position_value, stop_distance, constraint_applied
        """
        atr_str = request.args.get('atr')
        price_str = request.args.get('current_price')
        portfolio_str = request.args.get('portfolio_value')
        adv_str = request.args.get('avg_daily_volume_value')
        
        if not all([atr_str, price_str, portfolio_str]):
            abort(400, message="Missing required: atr, current_price, portfolio_value")
        
        try:
            atr = float(atr_str)
            current_price = float(price_str)
            portfolio_value = float(portfolio_str)
            avg_daily_volume = float(adv_str) if adv_str else None
        except ValueError:
            abort(400, message="Invalid numeric value")
        
        result = calculate_position_size(
            atr=atr,
            current_price=current_price,
            portfolio_value=portfolio_value,
            avg_daily_volume_value=avg_daily_volume
        )
        
        return result


@blp.route("/equal-weight-size")
class EqualWeightSize(MethodView):
    @blp.doc(tags=["Analysis"])
    def get(self):
        """
        Calculate equal-weight position size.
        
        Parameters:
            portfolio_value: Query param - Total portfolio value in INR
            max_positions: Query param - Maximum number of positions
            current_price: Query param - Current stock price
            
        Returns:
            Dict with shares, position_value
        """
        portfolio_str = request.args.get('portfolio_value')
        max_pos_str = request.args.get('max_positions')
        price_str = request.args.get('current_price')
        
        if not all([portfolio_str, max_pos_str, price_str]):
            abort(400, message="Missing required: portfolio_value, max_positions, "
                              "current_price")
        
        try:
            portfolio_value = float(portfolio_str)
            max_positions = int(max_pos_str)
            current_price = float(price_str)
        except ValueError:
            abort(400, message="Invalid numeric value")
        
        try:
            result = calculate_equal_weight_position(
                portfolio_value=portfolio_value,
                max_positions=max_positions,
                current_price=current_price
            )
        except ValueError as e:
            abort(400, message=str(e))
        
        return result

