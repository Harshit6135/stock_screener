from marshmallow import Schema, fields

class InstrumentSchema(Schema):
    isin = fields.Str()
    instrument_token = fields.Int(required=True)
    exchange_token = fields.Str()
    tradingsymbol = fields.Str()
    name = fields.Str(allow_none=True)
    exchange = fields.Str()
