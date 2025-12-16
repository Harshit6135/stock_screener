from marshmallow import Schema, fields


class ActionsSchema(Schema):
    id = fields.Int(dump_only=True)
    action_date = fields.Date(required=True)
    action_type = fields.Str(required=True)  # BUY, SELL, SWAP
    
    tradingsymbol = fields.Str(required=True)
    units = fields.Int(required=True)
    expected_price = fields.Float(allow_none=True)
    amount = fields.Float(allow_none=True)  # units × price
    composite_score = fields.Float(allow_none=True)
    
    # Buy range for gap-up protection
    buy_price_min = fields.Float(allow_none=True)
    buy_price_max = fields.Float(allow_none=True)
    
    swap_from_symbol = fields.Str(allow_none=True)
    swap_from_units = fields.Int(allow_none=True)
    swap_from_price = fields.Float(allow_none=True)
    
    status = fields.Str(load_default='PENDING')  # PENDING, INVESTED, SKIPPED, EXPIRED
    reason = fields.Str(allow_none=True)
    executed = fields.Bool(load_default=False)
    executed_at = fields.DateTime(allow_none=True)
    created_at = fields.DateTime(dump_only=True)


class GenerateActionsInputSchema(Schema):
    """Schema for triggering action generation"""
    ranking_date = fields.Date(required=False, load_default=None)


class ExecuteActionInputSchema(Schema):
    """Schema for executing an action with actual prices"""
    actual_buy_price = fields.Float(allow_none=True)
    actual_units = fields.Int(allow_none=True)
    actual_sell_price = fields.Float(allow_none=True)
