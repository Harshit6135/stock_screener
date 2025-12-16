from marshmallow import Schema, fields


class InvestedSchema(Schema):
    id = fields.Int(dump_only=True)
    tradingsymbol = fields.Str(required=True)
    instrument_token = fields.Int(allow_none=True)
    exchange = fields.Str(load_default="NSE")
    
    buy_price = fields.Float(required=True)
    num_shares = fields.Int(required=True)
    buy_date = fields.Date(allow_none=True)
    
    atr_at_entry = fields.Float(allow_none=True)
    initial_stop_loss = fields.Float(dump_only=True)
    current_stop_loss = fields.Float(dump_only=True)
    
    current_score = fields.Float(allow_none=True)
    last_updated = fields.DateTime(dump_only=True)
    
    investment_value = fields.Float(dump_only=True)
    include_in_strategy = fields.Bool(load_default=True)


class InvestedInputSchema(Schema):
    """Schema for adding new position - minimal input"""
    tradingsymbol = fields.Str(required=True)
    buy_price = fields.Float(required=True)
    num_shares = fields.Int(required=True)
    include_in_strategy = fields.Bool(load_default=True)
