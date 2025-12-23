from flask.views import MethodView
from flask_smorest import Blueprint, abort

from schemas import (
    RiskConfigSchema, 
    InvestedSchema, InvestedInputSchema,
    PortfolioSummarySchema,
    MessageSchema
)

from services import PortfolioService
from repositories import ConfigRepository, PortfolioRepository


config_repo = ConfigRepository()
portfolio_repo = PortfolioRepository()
blp = Blueprint("portfolio", __name__, url_prefix="/api/v1/portfolio",
                description="Portfolio management operations")


@blp.route("/risk_config")
class RiskConfig(MethodView):
    @blp.response(200, RiskConfigSchema)
    def get(self):
        """Get current risk configuration"""
        config = config_repo.get_config()
        return config

    @blp.arguments(RiskConfigSchema)
    @blp.response(200, RiskConfigSchema)
    def put(self, config_data):
        """Update risk configuration"""
        config = config_repo.get_config()
        if not config:
            config_repo.post_config(config_data)
        else:
            config_repo.update_config(config_data)
        return config_data


@blp.route("/summary")
class PortfolioSummary(MethodView):
    @blp.response(200, PortfolioSummarySchema)
    def get(self):
        """Get portfolio summary statistics"""
        portfolio_service = PortfolioService()
        response = portfolio_service.generate_portfolio_summary()
        return response


@blp.route("/invested")
class InvestedList(MethodView):
    @blp.response(200, InvestedSchema(many=True))
    def get(self):
        """Get all invested stocks with current rank"""
        portfolio_service = PortfolioService()
        return portfolio_service.get_invested_stocks()

    @blp.arguments(InvestedInputSchema)
    @blp.response(201, InvestedSchema)
    def post(self, invest_data):
        """Add a new invested stock with calculated stop-loss"""
        portfolio_service = PortfolioService()
        invested = portfolio_service.add_new_stock(invest_data)
        return invested

    @blp.response(200, MessageSchema)
    def delete(self):
        """Clear all invested stocks"""
        response = portfolio_repo.delete_all()
        if not response:
            abort(404, "No Invested Stock found")
        return response


@blp.route("/invested/<string:tradingsymbol>")
class InvestedItem(MethodView):

    @blp.response(200, InvestedSchema)
    def get(self, tradingsymbol):
        """Get specific invested stock"""
        invested = portfolio_repo.get_invested_by_symbol(tradingsymbol)
        if not invested:
            abort(404, message=f"Not invested in {tradingsymbol}")
        return invested

    @blp.response(200, MessageSchema)
    def delete(self, tradingsymbol):
        """Remove specific invested stock"""
        invested = portfolio_repo.delete_stock(tradingsymbol)
        if not invested:
            abort(404, message=f"Not invested in {tradingsymbol}")

        return invested