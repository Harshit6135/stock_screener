from marshmallow import Schema, fields


class PercentileSchema(Schema):
    """Schema for daily percentile ranks (renamed from RankingSchema)"""
    tradingsymbol = fields.Str(required=True)
    percentile_date = fields.Date(required=True)
    
    ema_50_slope = fields.Float(allow_none=True)
    trend_rank = fields.Float(allow_none=True)
    distance_from_ema_200 = fields.Float(allow_none=True)
    trend_extension_rank = fields.Float(allow_none=True)
    distance_from_ema_50 = fields.Float(allow_none=True)
    trend_start_rank = fields.Float(allow_none=True)
    rsi_signal_ema_3 = fields.Float(allow_none=True)
    momentum_rsi_rank = fields.Float(allow_none=True)
    ppo_12_26_9 = fields.Float(allow_none=True)
    momentum_ppo_rank = fields.Float(allow_none=True)
    ppoh_12_26_9 = fields.Float(allow_none=True)
    momentum_ppoh_rank = fields.Float(allow_none=True)
    risk_adjusted_return = fields.Float(allow_none=True)
    efficiency_rank = fields.Float(allow_none=True)
    rvol = fields.Float(allow_none=True)
    rvolume_rank = fields.Float(allow_none=True)
    price_vol_correlation = fields.Float(allow_none=True)
    price_vol_corr_rank = fields.Float(allow_none=True)
    bbb_20_2 = fields.Float(allow_none=True)
    structure_rank = fields.Float(allow_none=True)
    percent_b = fields.Float(allow_none=True)
    structure_bb_rank = fields.Float(allow_none=True)


class PercentileAllSchema(Schema):
    """Schema for querying all percentile data by date"""
    date = fields.Date()
