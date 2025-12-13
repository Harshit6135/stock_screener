from marshmallow import Schema, fields

class IndicatorsSchema(Schema):
    instrument_token = fields.Int(required=True)
    ticker = fields.Str(required=True)
    date = fields.Date(required=True)
    exchange = fields.Str(required=True)

    rsi_14 = fields.Float()
    ema_50 = fields.Float()
    ema_200 = fields.Float()
    macd = fields.Float()

