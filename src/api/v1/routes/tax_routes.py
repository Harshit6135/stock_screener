"""
Tax Routes

API endpoints for capital gains tax calculations.
Uses TaxConfig - no hardcoded values.
"""
from flask import request
from flask.views import MethodView
from flask_smorest import Blueprint, abort
from datetime import datetime

from src.utils.tax_utils import calculate_capital_gains_tax


blp = Blueprint(
    "tax", 
    __name__, 
    url_prefix="/api/v1/tax", 
    description="Tax Calculation Operations"
)


@blp.route("/estimate")
class TaxEstimate(MethodView):
    @blp.doc(tags=["Analysis"])
    def get(self):
        """
        Estimate capital gains tax for a trade.
        
        Used by backtesting API client.
        
        Parameters:
            purchase_price: Query param - Entry price per share
            current_price: Query param - Exit price per share
            purchase_date: Query param - Date of purchase (YYYY-MM-DD)
            current_date: Query param - Date of sale (YYYY-MM-DD)
            quantity: Query param - Number of shares
            
        Returns:
            Dict with gain, tax_type (STCG/LTCG), tax, net_gain
        """
        purchase_price_str = request.args.get('purchase_price')
        current_price_str = request.args.get('current_price')
        purchase_date_str = request.args.get('purchase_date')
        current_date_str = request.args.get('current_date')
        quantity_str = request.args.get('quantity')
        
        # Validate required params
        if not all([purchase_price_str, current_price_str, 
                    purchase_date_str, current_date_str, quantity_str]):
            abort(400, message="Missing required parameters: purchase_price, "
                              "current_price, purchase_date, current_date, quantity")
        
        # Parse values
        try:
            purchase_price = float(purchase_price_str)
            current_price = float(current_price_str)
            quantity = int(quantity_str)
        except ValueError:
            abort(400, message="Invalid numeric value")
        
        # Parse dates
        try:
            purchase_date = datetime.strptime(purchase_date_str, '%Y-%m-%d').date()
            current_date = datetime.strptime(current_date_str, '%Y-%m-%d').date()
        except ValueError:
            abort(400, message="Invalid date format. Use YYYY-MM-DD")
        
        # Calculate tax
        result = calculate_capital_gains_tax(
            purchase_price=purchase_price,
            current_price=current_price,
            purchase_date=purchase_date,
            current_date=current_date,
            quantity=quantity
        )
        
        return result
