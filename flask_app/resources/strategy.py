from flask import jsonify, request
from flask_smorest import Blueprint, abort
from flask.views import MethodView
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import and_, or_

from db import db

from models import MomentumStrategyModel
from schemas import MomentumStrategySchema

blp = Blueprint("strategy", __name__, description="get data for different strategies")

@blp.route("/momentumstrategy")
class MomentumStrategy(MethodView):
    @blp.response(200, MomentumStrategySchema(many=True))
    def get(self):
        return MomentumStrategyModel.query.all()

    @blp.arguments(MomentumStrategySchema)
    @blp.response(201, MomentumStrategySchema)
    def post(self, strategy_data):
        strategy = MomentumStrategyModel(**strategy_data)
        try:
            db.session.add(strategy)
            db.session.commit()
        except SQLAlchemyError:
            abort(500, message="An error occurred while inserting the strategy.")

        return strategy