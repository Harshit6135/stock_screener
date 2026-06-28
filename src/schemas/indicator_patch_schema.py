from marshmallow import Schema, fields, validate


class IndicatorPatchSchema(Schema):
    """Schema for the /indicators/patch endpoint."""

    indicators = fields.List(
        fields.String(),
        load_default=None,
        metadata={
            "description": (
                "List of indicator column names to compute and upsert. "
                "If omitted, all registered indicators are patched. "
                "Example: [\"adx_14\", \"mansfield_rs\", \"sortino_ratio\"]"
            )
        },
    )
