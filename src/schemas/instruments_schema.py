from marshmallow import Schema, fields

class InstrumentSchema(Schema):
    instrument_token = fields.Int(required=True)
    exchange_token = fields.Str()
    tradingsymbol = fields.Str()
    name = fields.Str(allow_none=True)
    exchange = fields.Str()
    market_cap = fields.Float()
    industry = fields.Str()
    sector = fields.Str()

class MessageSchema(Schema):
    message = fields.Str()
