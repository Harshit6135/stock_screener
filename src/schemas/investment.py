from marshmallow import Schema, fields


class ActionDateSchema(Schema):
    """Schema for action date response"""
    dates = fields.List(fields.Date(), dump_only=True)


class ActionQuerySchema(Schema):
    """Schema for querying actions by date"""
    date = fields.Date(required=False, load_default=None)


class ActionSchema(Schema):
    """Schema for action response"""
    action_id = fields.String(dump_only=True)
    working_date = fields.Date(dump_only=True)
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
