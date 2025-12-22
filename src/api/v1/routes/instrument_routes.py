from flask.views import MethodView
from flask_smorest import Blueprint, abort

from repositories import InstrumentsRepository
from schemas import InstrumentSchema, MessageSchema


blp = Blueprint("instruments", __name__, url_prefix="/api/v1/instruments", description="Operations on instruments")
instr_repository = InstrumentsRepository()


@blp.route("/")
class InstrumentList(MethodView):
    @blp.response(200, InstrumentSchema(many=True))
    def get(self):
        """Get all instruments"""
        instruments = instr_repository.get_all_instruments()
        return instruments

    @blp.arguments(InstrumentSchema(many=True))
    @blp.response(201, InstrumentSchema(many=True))
    def post(self, instrument_data):
        """Add multiple instruments"""
        response = instr_repository.bulk_insert(instrument_data)
        if response is None:
            abort(500, message="Failed to add instruments")
        return response

    @blp.response(200, MessageSchema)
    def delete(self):
        """Delete all instruments"""
        response = instr_repository.delete_all()
        if response == -1:
            abort(500, message="Failed to delete instruments")
        return {"message": f"Deleted all instruments."}


@blp.route("/<int:instrument_token>")
class Instrument(MethodView):
    @blp.response(200, InstrumentSchema)
    def get(self, instrument_token):
        """Get a task by instrument_token"""
        instrument = instr_repository.get_by_token(instrument_token)
        if instrument:
            return instrument
        abort(404, message="Instrument not found")


    @blp.arguments(InstrumentSchema)
    @blp.response(200, InstrumentSchema)
    def put(self, instrument_data, instrument_token):
        """Update a task by instrument_token"""
        instrument = instr_repository.update_instrument(instrument_token, instrument_data)
        if instrument and instrument != "FAILED":
            return instrument
        elif instrument == "FAILED":
            abort(500, message="Failed to update instrument")
        abort(404, message="Instrument not found")
