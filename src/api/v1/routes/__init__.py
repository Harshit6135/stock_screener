"""
API v1 Routes

Blueprints organized by category for Swagger UI navigation.
"""

# SYSTEM
from .init_routes import blp as init_bp
from .app_routes import blp as app_bp
from .config_routes import blp as config_bp

# DATA PIPELINE (in execution order)
from .instrument_routes import blp as instruments_bp
from .marketdata_routes import blp as marketdata_bp
from .indicators_routes import blp as indicators_bp
from .percentile_routes import blp as percentile_bp
from .score_routes import blp as score_bp
from .ranking_routes import blp as ranking_bp

# TRADING
from .actions_routes import blp as actions_bp
from .investment_routes import blp as investment_bp

# ANALYSIS
from .costs_routes import blp as costs_bp
from .tax_routes import blp as tax_bp
from .backtest_routes import blp as backtest_bp

__all__ = [
    "init_bp",
    "app_bp",
    "config_bp",
    "instruments_bp",
    "marketdata_bp",
    "indicators_bp",
    "percentile_bp",
    "score_bp",
    "ranking_bp",
    "actions_bp",
    "investment_bp",
    "costs_bp",
    "tax_bp",
    "backtest_bp",
]
