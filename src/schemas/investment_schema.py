"""
Investment Schemas

API schemas for holdings and summary endpoints.
Action schemas moved to schemas/actions.py for better separation.
"""
from marshmallow import Schema, fields


class HoldingDateSchema(Schema):
    """Schema for holding date response"""
    dates = fields.List(fields.Date(), dump_only=True)


class HoldingSchema(Schema):
    """Schema for holding response"""
    symbol = fields.String(dump_only=True)
    date = fields.Date(dump_only=True)
    entry_date = fields.Date(dump_only=True)
    entry_price = fields.Decimal(as_string=True, dump_only=True)
    units = fields.Integer(dump_only=True)
    atr = fields.Decimal(as_string=True, dump_only=True)
    score = fields.Decimal(as_string=True, dump_only=True)
    entry_sl = fields.Decimal(as_string=True, dump_only=True)
    current_price = fields.Decimal(as_string=True, dump_only=True)
    current_sl = fields.Decimal(as_string=True, dump_only=True)


class SummarySchema(Schema):
    """Schema for summary response"""
    date = fields.Date(dump_only=True)
    starting_capital = fields.Decimal(as_string=True, dump_only=True)
    sold = fields.Decimal(as_string=True, dump_only=True)
    bought = fields.Decimal(as_string=True, dump_only=True)
    capital_risk = fields.Decimal(as_string=True, dump_only=True)
    portfolio_value = fields.Decimal(as_string=True, dump_only=True)
    portfolio_risk = fields.Decimal(as_string=True, dump_only=True)
    gain = fields.Decimal(as_string=True, dump_only=True)
    gain_percentage = fields.Decimal(as_string=True, dump_only=True)
    remaining_capital = fields.Decimal(as_string=True, dump_only=True)
    invested_value = fields.Decimal(as_string=True, dump_only=True)
    unrealized_gain = fields.Decimal(as_string=True, dump_only=True)
    realized_gain = fields.Decimal(as_string=True, dump_only=True)
    absolute_return_pct = fields.Float(dump_only=True)
    xirr = fields.Float(dump_only=True)

class ManualBuySchema(Schema):
    symbol = fields.String(required=True, metadata={"description": "Trading symbol"})
    date = fields.Date(required=True, metadata={"description": "Action date (YYYY-MM-DD)"})
    reason = fields.String(load_default="Manual buy", metadata={"description": "Reason for trade"})
    config_name = fields.String(load_default="momentum_config", metadata={"description": "Config name for config"})
    units = fields.Integer(required=True, metadata={"description": "Number of units to buy"})
    price = fields.Decimal(required=True, metadata={"description": "Price of the stock"})


class ManualSellSchema(Schema):
    symbol = fields.String(required=True, metadata={"description": "Trading symbol"})
    date = fields.Date(required=True, metadata={"description": "Action date (YYYY-MM-DD)"})
    units = fields.Integer(required=True, metadata={"description": "Number of units to sell"})
    reason = fields.String(load_default="Manual sell", metadata={"description": "Reason for trade"})
    price = fields.Float(required=True, metadata={"description": "Price of the stock"})


class CapitalEventSchema(Schema):
    id = fields.Integer(dump_only=True)
    date = fields.Date(
        required=True,
        metadata={"description": "Event date (YYYY-MM-DD)"}
    )
    amount = fields.Float(
        required=True,
        metadata={
            "description": "Amount (positive=infusion)",
            "example": 100000,
        }
    )
    event_type = fields.String(
        required=True,
        metadata={
            "description": "initial | infusion | withdrawal",
            "example": "infusion",
        }
    )
    note = fields.String(
        load_default="",
        metadata={"description": "Optional note"}
    )