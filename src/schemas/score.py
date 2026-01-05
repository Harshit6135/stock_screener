from marshmallow import Schema, fields


class ScoreSchema(Schema):
    """Schema for daily composite scores"""
    tradingsymbol = fields.Str(required=True)
    score_date = fields.Date(required=True)

    final_trend_score = fields.Float(allow_none=True)
    final_momentum_score = fields.Float(allow_none=True)
    final_vol_score = fields.Float(allow_none=True)
    final_structure_score = fields.Float(allow_none=True)
    composite_score = fields.Float(required=True)
