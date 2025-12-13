from flask import jsonify, request
from flask_smorest import Blueprint, abort
from flask.views import MethodView
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import and_, func, desc, or_

from db import db
from models import InstrumentModel
from schemas import InstrumentSchema

blp = Blueprint("instruments", __name__, description="Operations on instruments")

@blp.route("/instruments")
class InstrumentList(MethodView):
    @blp.response(200, InstrumentSchema(many=True))
    def get(self):
        """Get all instruments"""
        instruments = InstrumentModel.query.all()
        return instruments

    @blp.arguments(InstrumentSchema(many=True))
    @blp.response(201, InstrumentSchema(many=True))
    def post(self, instrument_data):
        """Add multiple instruments"""
        try:
            db.session.bulk_insert_mappings(InstrumentModel, instrument_data, return_defaults=True)
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            abort(500, message=str(e))
        return instrument_data


@blp.route("/instruments/<int:instrument_token>")
class Instrument(MethodView):
    @blp.response(200, InstrumentSchema)
    def get(self, instrument_token):
        """Get a task by instrument_token"""
        instrument = InstrumentModel.query.get(instrument_token)
        if instrument:
            return instrument
        abort(404, message="Instrument not found")


    @blp.arguments(InstrumentSchema)
    @blp.response(200, InstrumentSchema)
    def put(self, instrument_data, instrument_token):
        """Update a task by instrument_token"""
        instrument = InstrumentModel.query.get(instrument_token)
        if instrument:
            for field, value in instrument_data.items():
                setattr(instrument, field, value)
            try:
                db.session.commit()
            except SQLAlchemyError as e:
                db.session.rollback()
                abort(500, message=str(e))
            return instrument
        abort(404, message="Instrument not found")
