from marshmallow import Schema, fields


class RiskConfigSchema(Schema):
    id = fields.Int(dump_only=True)
    initial_capital = fields.Float(load_default=100000.0)
    current_capital = fields.Float(load_default=100000.0)
    risk_per_trade = fields.Float(load_default=1000.0)
    max_positions = fields.Int(load_default=15)
    buffer_percent = fields.Float(load_default=0.25)
    exit_threshold = fields.Float(load_default=40.0)
    stop_loss_multiplier = fields.Float(load_default=2.0)
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)
