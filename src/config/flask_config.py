class Config:
    SQLALCHEMY_DATABASE_URI = "sqlite:///market_data.db"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    API_TITLE = "Stocks Screener"
    API_VERSION = "v1"
    OPENAPI_VERSION = "3.0.3"
    OPENAPI_URL_PREFIX = "/"
    OPENAPI_SWAGGER_UI_PATH = "/swagger-ui"
    OPENAPI_SWAGGER_UI_URL = "https://cdn.jsdelivr.net/npm/swagger-ui-dist/"
    OPENAPI_REDOC_PATH = "/redoc"
    OPENAPI_REDOC_URL = "https://cdn.jsdelivr.net/npm/redoc@latest/bundles/redoc.standalone.js"
    API_SPEC_OPTIONS = {
        "tags": [
            # System & Config
            {"name": "Initialization", "description": "Initialize App"},
            {"name": "App Orchestration", "description": "Application Orchestration & Cleanup Operations"},
            {"name": "Configuration", "description": "Configuration Management"},
            # Data Pipeline
            {"name": "Instruments", "description": "Operations on instruments"},
            {"name": "Market Data", "description": "Operations on market data"},
            {"name": "Indicators", "description": "Operations on indicators"},
            {"name": "Percentiles", "description": "Operations on Percentile Ranks"},
            {"name": "Scores", "description": "Operations on Score calculations"},
            {"name": "Rankings", "description": "Operations on Weekly Rankings"},
            # Trading
            {"name": "Actions", "description": "Trading Actions Operations"},
            {"name": "Investments", "description": "Investment Operations"},
            # Analysis
            {"name": "Transaction Costs", "description": "Transaction Cost and Sizing Calculations"},
            {"name": "Tax Analysis", "description": "Tax Calculation Operations"},
            # Backtest
            {"name": "Backtest", "description": "Backtesting Operations"},
        ],
        "x-tagGroups": [
            {"name": "System & Config", "tags": ["Initialization", "App Orchestration", "Configuration"]},
            {"name": "Data Pipeline", "tags": ["Instruments", "Market Data", "Indicators", "Percentiles", "Scores", "Rankings"]},
            {"name": "Trading", "tags": ["Actions", "Investments"]},
            {"name": "Analysis", "tags": ["Transaction Costs", "Tax Analysis"]},
            {"name": "Backtest", "tags": ["Backtest"]}
        ]
    }
    SQLALCHEMY_BINDS = {
        "personal": "sqlite:///personal.db",
        "backtest": "sqlite:///backtest.db"
    }
