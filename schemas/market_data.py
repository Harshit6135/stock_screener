from marshmallow import Schema, fields, validates_schema, ValidationError

class MarketDataSchema(Schema):
    instrument_token = fields.Int(required=True)
    tradingsymbol = fields.Str(required=True)
    exchange = fields.Str(required=True)
    date = fields.Date(required=True)
    open = fields.Float()
    high = fields.Float()
    low = fields.Float()
    close = fields.Float()
    volume = fields.Float()

class MarketDataQuerySchema(Schema):
    instrument_token = fields.Int()
    tradingsymbol = fields.Str()
    start_date = fields.Date(required=True)
    end_date = fields.Date(required=True)

    @validates_schema
    def validate_instrument(self, data, **kwargs):
        if "instrument_token" not in data and "tradingsymbol" not in data:
            raise ValidationError("Either instrument_token or ticker must be provided.")

class MaxDateSchema(Schema):
    instrument_token = fields.Int(required=True)
    max_date = fields.Date(required=True)

class LatestMarketDataQuerySchema(Schema):
    instrument_token = fields.Int()
    tradingsymbol = fields.Str()

    @validates_schema
    def validate_instrument(self, data, **kwargs):
        if "instrument_token" not in data and "tradingsymbol" not in data:
            raise ValidationError("Either instrument_token or tradingsymbol must be provided.")
