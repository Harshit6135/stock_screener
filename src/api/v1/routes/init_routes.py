from flask.views import MethodView
from flask_smorest import Blueprint, abort

from services import InitService
from schemas import InitResponseSchema


blp = Blueprint("init", __name__, url_prefix="/api/v1/init", description="Initialize App")


@blp.route("/")
class Init(MethodView):
    @blp.doc(tags=["System"])
    @blp.response(201, InitResponseSchema)
    def post(self):
        """Initialize App"""
        try:
            init_service = InitService()
            response_code, response = init_service.initialize_app()
            if response_code not in [200, 201]:
                abort(response_code, message="Initialization failed during Kite sync")
        except Exception as e:
            abort(500, message=str(e))
        return response
