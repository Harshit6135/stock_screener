from marshmallow import Schema, fields


class CleanupQuerySchema(Schema):
    """Schema for cleanup query parameters"""
    start_date = fields.Date(required=True, metadata={"description": "Delete all data after this date (YYYY-MM-DD)"})
