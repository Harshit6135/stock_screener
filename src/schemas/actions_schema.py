"""
Actions Schemas

API schemas for trading actions endpoints.
Separated from investment schemas for clarity.
"""
from marshmallow import Schema, fields


class ActionDateSchema(Schema):
    """Schema for action date response"""
    dates = fields.List(fields.Date(), dump_only=True)


class ActionQuerySchema(Schema):
    """Schema for querying actions by date and strategy"""
    date = fields.Date(required=False, load_default=None)
    strategy_name = fields.String(required=False, load_default="momentum_strategy_one")


class ActionSchema(Schema):
    """Schema for action response"""
    action_id = fields.String(dump_only=True)
    action_date = fields.Date(dump_only=True)
    type = fields.String(dump_only=True)
    reason = fields.String(dump_only=True)
    symbol = fields.String(dump_only=True)
    risk = fields.Decimal(as_string=True, dump_only=True)
    atr = fields.Decimal(as_string=True, dump_only=True)
    units = fields.Integer(dump_only=True)
    prev_close = fields.Decimal(as_string=True, dump_only=True)
    execution_price = fields.Decimal(as_string=True, dump_only=True)
    capital = fields.Decimal(as_string=True, dump_only=True)
    status = fields.String(dump_only=True)


class ActionUpdateSchema(Schema):
    """Schema for updating an action"""
    status = fields.String(
        required=True,
        metadata={"description": "New status: Approved or Rejected"}
    )
    units = fields.Integer(
        required=False,
        metadata={"description": "Updated number of units"}
    )
    execution_price = fields.Decimal(
        as_string=True,
        required=False,
        metadata={"description": "Execution price (required for approval)"}
    )
