from marshmallow import Schema, fields

class IndicatorsSchema(Schema):
    instrument_token = fields.Int(required=True)
    tradingsymbol = fields.Str(required=True)
    date = fields.Date(required=True)
    exchange = fields.Str(required=True)

    ema_50 = fields.Float(allow_none=True)
    ema_200 = fields.Float(allow_none=True)
    rsi_14_3 = fields.Float(allow_none=True)
    rsi_14_3_signal = fields.Float(allow_none=True)
    roc_10 = fields.Float(allow_none=True)
    stoch_14_3_k = fields.Float(allow_none=True)
    stoch_14_3_d = fields.Float(allow_none=True)
    bbands_20_2_125_lower = fields.Float(allow_none=True)
    bbands_20_2_125_upper = fields.Float(allow_none=True)
    bbands_20_2_125_sma = fields.Float(allow_none=True)
    bbands_20_2_125_bbw = fields.Float(allow_none=True)
    bbands_20_2_125_hist_low = fields.Float(allow_none=True)
    macd_12_26_9 = fields.Float(allow_none=True)
    macd_12_26_9_signal = fields.Float(allow_none=True)
    volume_5 = fields.Float(allow_none=True)
    volume_20 = fields.Float(allow_none=True)
