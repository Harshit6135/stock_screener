from marshmallow import Schema, fields, validates_schema, ValidationError

class MarketDataSchema(Schema):
    instrument_id = fields.Int(required=True)
    ticker = fields.Str(required=True)
    exchange = fields.Str(required=True)
    date = fields.Date(required=True)
    open = fields.Float()
    high = fields.Float()
    low = fields.Float()
    close = fields.Float()
    volume = fields.Float()

class MarketDataQuerySchema(Schema):
    instrument_id = fields.Int()
    ticker = fields.Str()
    start_date = fields.Date(required=True)
    end_date = fields.Date(required=True)

    @validates_schema
    def validate_instrument(self, data, **kwargs):
        if "instrument_id" not in data and "ticker" not in data:
            raise ValidationError("Either instrument_id or ticker must be provided.")

class MaxDateSchema(Schema):
    instrument_id = fields.Int(required=True)
    max_date = fields.Date(required=True)

class LatestMarketDataQuerySchema(Schema):
    instrument_id = fields.Int()
    ticker = fields.Str()

    @validates_schema
    def validate_instrument(self, data, **kwargs):
        if "instrument_id" not in data and "ticker" not in data:
            raise ValidationError("Either instrument_id or ticker must be provided.")
