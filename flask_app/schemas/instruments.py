from marshmallow import Schema, fields

class InstrumentSchema(Schema):
    instrument_token = fields.Int(required=True)
    exchange_token = fields.Str()
    tradingsymbol = fields.Str()
    name = fields.Str()
    last_price = fields.Float()
    expiry = fields.Str()
    strike = fields.Float()
    tick_size = fields.Float()
    lot_size = fields.Int()
    instrument_type = fields.Str()
    segment = fields.Str()
    exchange = fields.Str()
