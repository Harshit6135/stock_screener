from marshmallow import Schema, fields


class InitResponseSchema(Schema):
    nse_count = fields.Int(required=True)
    bse_count = fields.Int(required=True)
    merged_count = fields.Int(required=True)
    final_count = fields.Int(required=True)
