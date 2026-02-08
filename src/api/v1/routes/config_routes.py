"""
Configuration API Routes

GET/PUT endpoints for runtime configuration management.
"""
from flask.views import MethodView
from flask_smorest import Blueprint

from schemas import RiskConfigSchema
from repositories import ConfigRepository

blp = Blueprint(
    "config",
    __name__,
    url_prefix="/api/v1/config",
    description="Configuration Management"
)


@blp.route("/<string:strategy_name>")
class StrategyConfigResource(MethodView):
    """Runtime configuration for trading strategies"""

    @blp.doc(tags=["System"])
    @blp.response(200, RiskConfigSchema)
    def get(self, strategy_name: str):
        """
        Get current strategy configuration.

        Parameters:
            strategy_name (str): Strategy identifier (e.g., 'momentum_strategy_one')

        Returns:
            RiskConfigSchema: Current configuration values
        """
        config_repo = ConfigRepository()
        config = config_repo.get_config(strategy_name)
        if config is None:
            return {"message": f"Configuration not found for {strategy_name}"}, 404
        return config

    @blp.doc(tags=["System"])
    @blp.arguments(RiskConfigSchema)
    @blp.response(200, RiskConfigSchema)
    def put(self, data: dict, strategy_name: str):
        """
        Update strategy configuration at runtime.

        Parameters:
            strategy_name (str): Strategy identifier
            data (dict): Configuration values to update

        Returns:
            RiskConfigSchema: Updated configuration
        """
        config_repo = ConfigRepository()
        existing = config_repo.get_config(strategy_name)
        if existing is None:
            return {"message": f"Configuration not found for {strategy_name}"}, 404
        
        # Update only provided fields
        config_repo.update_config(data)
        return config_repo.get_config(strategy_name)
