from sqlalchemy import PrimaryKeyConstraint

from db import db


class IndicatorsModel(db.Model):
    __tablename__ = "indicators"

    tradingsymbol = db.Column(db.String, nullable=False)
    date = db.Column(db.Date, nullable=False)
    exchange = db.Column(db.String, nullable=False)

    ema_50 = db.Column(db.Float, nullable=True)
    ema_200 = db.Column(db.Float, nullable=True)
    rsi_14 = db.Column(db.Float, nullable=True)
    roc_10 = db.Column(db.Float, nullable=True)
    roc_20 = db.Column(db.Float, nullable=True)
    sma_20 = db.Column(db.Float, nullable=True)
    stochk_14_3_3 = db.Column(db.Float, nullable=True)
    stochd_14_3_3 = db.Column(db.Float, nullable=True)
    stochh_14_3_3 = db.Column(db.Float, nullable=True)
    ppo_12_26_9 = db.Column(db.Float, nullable=True)
    ppoh_12_26_9 = db.Column(db.Float, nullable=True)
    ppos_12_26_9 = db.Column(db.Float, nullable=True)
    macd_12_26_9 = db.Column(db.Float, nullable=True)
    macdh_12_26_9 = db.Column(db.Float, nullable=True)
    macds_12_26_9 = db.Column(db.Float, nullable=True)
    bbl_20_2_2 = db.Column(db.Float, nullable=True)
    bbm_20_2_2 = db.Column(db.Float, nullable=True)
    bbu_20_2_2 = db.Column(db.Float, nullable=True)
    bbb_20_2_2 = db.Column(db.Float, nullable=True)
    bbp_20_2_2 = db.Column(db.Float, nullable=True)
    atrr_14 = db.Column(db.Float, nullable=True)
    rsi_signal_ema_3 = db.Column(db.Float, nullable=True)
    vol_sma_20 = db.Column(db.Float, nullable=True)
    price_vol_correlation = db.Column(db.Float, nullable=True)
    percent_b = db.Column(db.Float, nullable=True)
    ema_50_slope = db.Column(db.Float, nullable=True)
    distance_from_ema_200 = db.Column(db.Float, nullable=True)
    distance_from_ema_50 = db.Column(db.Float, nullable=True)
    risk_adjusted_return = db.Column(db.Float, nullable=True)
    rvol = db.Column(db.Float, nullable=True)
    roc_60 = db.Column(db.Float, nullable=True)
    roc_125 = db.Column(db.Float, nullable=True)
    atr_spike = db.Column(db.Float, nullable=True)
    momentum_3m = db.Column(db.Float, nullable=True)
    momentum_6m = db.Column(db.Float, nullable=True)
    avg_turnover_ema_20 = db.Column(db.Float, nullable=True)

    # ── Strategy 2 indicators (nullable; populated via /indicators/patch) ──
    adx_14 = db.Column(db.Float, nullable=True)             # ADX regime multiplier
    mansfield_rs = db.Column(db.Float, nullable=True)       # Mansfield RS vs Nifty 500
    nse_norm_momentum = db.Column(db.Float, nullable=True)  # Vol-adj 6M+12M momentum ratio
    sortino_ratio = db.Column(db.Float, nullable=True)      # Sortino Ratio (rf=6%, annualised)
    scaled_turnover = db.Column(db.Float, nullable=True)    # Illiquidity proxy (lower = better)
    log_price_vol_corr = db.Column(db.Float, nullable=True) # 20-day log-return price-vol corr
    momentum_12m = db.Column(db.Float, nullable=True)       # 12M skip-5 return
    quality_z_score = db.Column(db.Float, nullable=True)    # Fundamental quality composite

    __table_args__ = (
        # composite primary key
        PrimaryKeyConstraint("tradingsymbol", "date"),
    )

    def __repr__(self):
        return f"<Indicator {self.tradingsymbol} {self.date}>"
