from marshmallow import Schema, fields


class InitRequestSchema(Schema):
    yfinance_batch_size = fields.Int(
        load_default=100,
        metadata={"description": "Number of stocks to fetch before sleeping"}
    )
    yfinance_sleep_time = fields.Int(
        load_default=4,
        metadata={"description": "Seconds to sleep between YFinance batches"}
    )


class InitResponseSchema(Schema):
    nse_count = fields.Int(required=True)
    bse_count = fields.Int(required=True)
    merged_count = fields.Int(required=True)
    final_count = fields.Int(required=True)
