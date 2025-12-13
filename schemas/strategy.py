from marshmallow import Schema, fields

class MomentumStrategySchema(Schema):
    ticker = fields.Str(required=True)
    mcap = fields.Float()
    price_check = fields.Bool()
    squeeze_check = fields.Bool()
    rsi_check = fields.Bool()
    rsi_bullish = fields.Bool()
    roc_check = fields.Bool()
    macd_check = fields.Bool()
    stoch_check = fields.Bool()
    stoch_cross = fields.Bool()
    vol_check = fields.Bool()

    squeeze_setup = fields.Bool()
    momentum_setup = fields.Bool()

    setup_type = fields.Str()
    status = fields.Str()
    summary = fields.Str()

