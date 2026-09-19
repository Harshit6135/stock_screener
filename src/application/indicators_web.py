"""Read-only API for the future indicator catalogue UI."""

from flask import Blueprint, jsonify

from src.indicators.registry import PandasTaAdapter
from src.platform_kernel import DomainValidationError


def create_indicators_blueprint(adapter: PandasTaAdapter) -> Blueprint:
    blueprint = Blueprint("indicators_v2", __name__, url_prefix="/api/v2/indicators")

    @blueprint.get("/catalog")
    def catalogue():
        return jsonify({"indicators": adapter.catalogue()})

    @blueprint.get("/catalog/pandas_ta/<indicator_key>")
    def detail(indicator_key: str):
        try:
            return jsonify(adapter.spec(indicator_key).catalogue_item(adapter.package_version, adapter.adapter_version))
        except DomainValidationError as exc:
            return jsonify({"error": str(exc)}), 404

    return blueprint
