from marshmallow import Schema, fields


class CleanupQuerySchema(Schema):
    """Schema for cleanup query parameters with per-table toggles."""
    start_date = fields.Date(
        required=True,
        metadata={
            "description": "Delete all data after this date (YYYY-MM-DD)",
            "example": "2025-01-01",
        }
    )
    marketdata = fields.Boolean(
        load_default=True,
        metadata={
            "description": "Delete from marketdata table",
            "example": True,
        }
    )
    indicators = fields.Boolean(
        load_default=True,
        metadata={
            "description": "Delete from indicators table",
            "example": True,
        }
    )
    percentile = fields.Boolean(
        load_default=True,
        metadata={
            "description": "Delete from percentile table",
            "example": True,
        }
    )
    score = fields.Boolean(
        load_default=True,
        metadata={
            "description": "Delete from score table",
            "example": True,
        }
    )
    ranking = fields.Boolean(
        load_default=True,
        metadata={
            "description": "Delete from ranking table",
            "example": True,
        }
    )


class PipelineQuerySchema(Schema):
    """Schema for pipeline run toggles — choose which steps to execute."""
    init = fields.Boolean(
        load_default=True,
        metadata={
            "description": "Run init app (instruments setup)",
            "example": True,
        }
    )
    marketdata = fields.Boolean(
        load_default=True,
        metadata={
            "description": "Run market data update",
            "example": True,
        }
    )
    historical = fields.Boolean(
        load_default=False,
        metadata={
            "description": (
                "If true, fetch full historical data for market data "
                "step (default: latest only)"
            ),
            "example": False,
        }
    )
    indicators = fields.Boolean(
        load_default=True,
        metadata={
            "description": "Run indicators calculation",
            "example": True,
        }
    )
    percentile = fields.Boolean(
        load_default=True,
        metadata={
            "description": "Run percentile calculation",
            "example": True,
        }
    )
    score = fields.Boolean(
        load_default=True,
        metadata={
            "description": "Run composite score calculation",
            "example": True,
        }
    )
    ranking = fields.Boolean(
        load_default=True,
        metadata={
            "description": "Run ranking calculation",
            "example": True,
        }
    )
    yfinance_batch_size = fields.Integer(
        load_default=100,
        metadata={
            "description": "Number of stocks to fetch before sleeping (YFinance API limit safeguard)",
            "example": 100,
        }
    )
    yfinance_sleep_time = fields.Integer(
        load_default=4,
        metadata={
            "description": "Seconds to sleep between YFinance batches",
            "example": 4,
        }
    )


class RecalculateQuerySchema(Schema):
    """Schema for recalculate-from-date with per-table toggles."""
    start_date = fields.Date(
        required=True,
        metadata={
            "description": (
                "Recalculate all data from this date onwards "
                "(YYYY-MM-DD)"
            ),
            "example": "2025-01-01",
        }
    )
    percentile = fields.Boolean(
        load_default=True,
        metadata={
            "description": "Recalculate percentiles from start_date",
            "example": True,
        }
    )
    score = fields.Boolean(
        load_default=True,
        metadata={
            "description": "Recalculate composite scores from start_date",
            "example": True,
        }
    )
    ranking = fields.Boolean(
        load_default=True,
        metadata={
            "description": "Recalculate rankings from start_date",
            "example": True,
        }
    )
