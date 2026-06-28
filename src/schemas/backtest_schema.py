from marshmallow import Schema, fields, validate


class BacktestInputSchema(Schema):
    """Schema for backtest input parameters"""

    start_date = fields.Date(required=True, metadata={"description": "Backtest start date"})
    end_date = fields.Date(required=True, metadata={"description": "Backtest end date"})
    config_name = fields.String(
        required=False,
        load_default="momentum_config",
        metadata={"description": "config name for config lookup"},
    )
    check_daily_sl = fields.Boolean(
        load_default=True,
        metadata={"description": ("Check stop-loss daily (True) or " "weekly on Monday (False)")},
    )
    mid_week_buy = fields.Boolean(
        load_default=True,
        metadata={
            "description": (
                "Fill pending buys mid-week when " "vacancy exists (True) or skip (False)"
            )
        },
    )
    run_label = fields.String(
        required=False,
        load_default=None,
        metadata={"description": "Optional label/name for this backtest run"},
    )
    enable_pyramiding = fields.Boolean(
        load_default=False,
        metadata={
            "description": ("Enable pyramiding (adding to winning " "positions still in top N)")
        },
    )
    strategy_id = fields.String(
        load_default="strategy1",
        validate=validate.OneOf(["strategy1", "strategy2"]),
        metadata={
            "description": (
                "Which strategy's rankings to use for this backtest. "
                "strategy1 = original momentum strategy (default). "
                "strategy2 = institutional multi-factor framework."
            )
        },
    )
