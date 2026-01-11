from marshmallow import Schema, fields


class BacktestInputSchema(Schema):
    """Schema for backtest input parameters"""
    start_date = fields.Date(required=True, metadata={"description": "Backtest start date"})
    end_date = fields.Date(required=True, metadata={"description": "Backtest end date"})

