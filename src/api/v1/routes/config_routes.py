"""
Configuration API Routes

GET/POST/PUT endpoints for runtime configuration management.
"""
from flask.views import MethodView
from flask_smorest import Blueprint, abort

from schemas import ConfigSchema
from repositories import ConfigRepository

blp = Blueprint(
    "Configuration",
    __name__,
    url_prefix="/api/v1/config",
    description="Configuration Management"
)


@blp.route("/<string:config_name>")
class ConfigResource(MethodView):
    """Runtime configuration for trading strategies"""

    @blp.doc(tags=["Configuration"])
    @blp.response(200, ConfigSchema)
    def get(self, config_name: str):
        """
        Get current strategy configuration.

        Parameters:
            config_name (str): Strategy identifier (e.g., 'momentum_strategy_one')

        Returns:
            ConfigSchema: Current configuration values
        """
        config_repo = ConfigRepository()
        config = config_repo.get_config(config_name)
        if config is None:
            abort(404, message=f"Configuration not found for {config_name}")
        return config

    @blp.doc(tags=["Configuration"])
    @blp.arguments(ConfigSchema)
    @blp.response(200, ConfigSchema)
    def put(self, data: dict, config_name: str):
        """
        Update strategy configuration at runtime.

        Parameters:
            config_name (str): Strategy identifier
            data (dict): Configuration values to update

        Returns:
            ConfigSchema: Updated configuration
        """
        config_repo = ConfigRepository()
        existing = config_repo.get_config(config_name)
        if existing is None:
            abort(404, message=f"Configuration not found for {config_name}")
        
        # Update only provided fields
        config_repo.update_config(data)
        return config_repo.get_config(config_name)

    @blp.doc(tags=["Configuration"])
    @blp.arguments(ConfigSchema)
    @blp.response(201, ConfigSchema)
    def post(self, data: dict, config_name: str):
        """
        Create a new configuration.

        Parameters:
            config_name (str): Configuration identifier (e.g., 'momentum_config')
            data (dict): Configuration values to create

        Returns:
            ConfigSchema: Newly created configuration
        """
        config_repo = ConfigRepository()
        existing = config_repo.get_config(config_name)
        if existing is not None:
            return {"message": f"Configuration already exists for {config_name}"}, 409

        data["config_name"] = config_name
        config_repo.post_config(data)
        return config_repo.get_config(config_name)
