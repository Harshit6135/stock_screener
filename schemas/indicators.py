from marshmallow import Schema, fields

class IndicatorsSchema(Schema):
    instrument_token = fields.Int(required=True)
    ticker = fields.Str(required=True)
    date = fields.Date(required=True)
    exchange = fields.Str(required=True)

    rsi_14 = fields.Float(allow_none=True)
    ema_50 = fields.Float(allow_none=True)
    ema_200 = fields.Float(allow_none=True)
    macd = fields.Float(allow_none=True)

