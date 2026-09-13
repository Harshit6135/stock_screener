"""Operator-protected broker order intent and reconciliation endpoints."""

from flask import Blueprint, jsonify, request

from src.application.web import require_operator_token
from src.execution_gateway import BrokerOrderService
from src.platform_kernel import DomainValidationError


def create_broker_blueprint(orders: BrokerOrderService) -> Blueprint:
    blueprint = Blueprint("broker_v2", __name__, url_prefix="/api/v2/portfolio")

    @blueprint.before_request
    def authorize():
        error = require_operator_token()
        return (jsonify(error[0]), error[1]) if error else None

    @blueprint.post("/orders")
    def create():
        try:
            return jsonify(orders.create_intent(request.get_json(silent=True))), 201
        except DomainValidationError as exc:
            return jsonify({"error": str(exc)}), 400

    @blueprint.get("/execution-controls")
    def execution_controls():
        return jsonify(orders.execution_controls())

    @blueprint.post("/baskets")
    def create_basket():
        try:
            return jsonify(orders.create_basket(request.get_json(silent=True))), 201
        except DomainValidationError as exc:
            return jsonify({"error": str(exc)}), 400

    @blueprint.get("/baskets/<basket_id>")
    def get_basket(basket_id: str):
        try:
            return jsonify(orders.basket(basket_id))
        except DomainValidationError:
            return jsonify({"error": "broker basket not found"}), 404

    @blueprint.post("/baskets/<basket_id>/submit")
    def submit_basket(basket_id: str):
        try:
            body = request.get_json(silent=True) or {}
            return jsonify(orders.submit_basket(basket_id, body.get("slice_index", 0))), 202
        except DomainValidationError as exc:
            return jsonify({"error": str(exc)}), 409

    @blueprint.get("/orders/<order_id>")
    def get(order_id: str):
        try:
            return jsonify(orders.get(order_id))
        except DomainValidationError:
            return jsonify({"error": "broker order not found"}), 404

    @blueprint.post("/orders/<order_id>/submit")
    def submit(order_id: str):
        try:
            return jsonify(orders.submit(order_id)), 202
        except DomainValidationError as exc:
            return jsonify({"error": str(exc)}), 409

    @blueprint.post("/orders/<order_id>/reconcile")
    def reconcile(order_id: str):
        try:
            return jsonify(orders.reconcile(order_id)), 202
        except DomainValidationError as exc:
            return jsonify({"error": str(exc)}), 409

    @blueprint.post("/orders/<order_id>/manual-fill")
    def manual_fill(order_id: str):
        try:
            return jsonify(orders.manual_fill(order_id, request.get_json(silent=True))), 201
        except DomainValidationError as exc:
            return jsonify({"error": str(exc)}), 409

    return blueprint
