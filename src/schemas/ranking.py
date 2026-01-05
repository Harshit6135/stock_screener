from marshmallow import Schema, fields


class RankingSchema(Schema):
    """Schema for weekly rankings (renamed from AvgScoreSchema)"""
    tradingsymbol = fields.Str(required=True)
    ranking_date = fields.Date(required=True)
    composite_score = fields.Float(required=True)
    rank = fields.Int(required=True)


class TopNSchema(Schema):
    """Simplified schema for top N display"""
    tradingsymbol = fields.Str()
    composite_score = fields.Float()
    rank = fields.Int()
    is_invested = fields.Bool()
    ranking_date = fields.Date()
    close_price = fields.Float(allow_none=True)
