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
    working_date = fields.Date(dump_only=True)
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
    working_date = fields.Date(dump_only=True)
    starting_capital = fields.Decimal(as_string=True, dump_only=True)
    sold = fields.Decimal(as_string=True, dump_only=True)
    bought = fields.Decimal(as_string=True, dump_only=True)
    capital_risk = fields.Decimal(as_string=True, dump_only=True)
    portfolio_value = fields.Decimal(as_string=True, dump_only=True)
    portfolio_risk = fields.Decimal(as_string=True, dump_only=True)
    gain = fields.Decimal(as_string=True, dump_only=True)
    gain_percentage = fields.Decimal(as_string=True, dump_only=True)
    remaining_capital = fields.Decimal(as_string=True, dump_only=True)
