from marshmallow import Schema, fields


class ConfigSchema(Schema):
    id = fields.Int(dump_only=True)
    config_name = fields.Str(dump_only=True)

    initial_capital = fields.Float(load_default=100000.0)
    risk_threshold = fields.Float(load_default=1.0)
    max_positions = fields.Int(load_default=15)
    buffer_percent = fields.Float(load_default=0.25)
    exit_threshold = fields.Float(load_default=40.0)
    sl_multiplier = fields.Float(load_default=2.0)
    sl_step_percent = fields.Float(load_default=0.10)
    atr_fallback_percent = fields.Float(load_default=0.03)
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)
