from db import db
from flask_smorest import Api
from flask_migrate import Migrate
from flask import Flask, render_template

from config import Config
from src.api.v1.routes import (
    actions_bp,
    instruments_bp,
    marketdata_bp,
    indicators_bp,
    portfolio_bp,
    ranking_bp,
    init_bp
)


def create_app(config_class=Config):
    """Application factory"""
    app = Flask(__name__)
    app.config.from_object(config_class)
    return app

app = create_app()
db.init_app(app)
migrate = Migrate(app, db)
api = Api(app)

# Create all database tables
with app.app_context():
    db.create_all()

# Register API blueprints
api.register_blueprint(init_bp)
api.register_blueprint(instruments_bp)
api.register_blueprint(marketdata_bp)
api.register_blueprint(indicators_bp)
api.register_blueprint(actions_bp)
api.register_blueprint(ranking_bp)
api.register_blueprint(portfolio_bp)


# Main Dashboard Route
@app.route("/")
def dashboard():
    """Render the main dashboard"""
    return render_template('dashboard.html')

@app.route("/actions")
def actions():
    from datetime import date, timedelta
    import math
    import pandas as pd

    from src.repositories import RankingRepository
    from src.repositories import IndicatorsRepository
    from src.repositories import MarketDataRepository
    ranking = RankingRepository()
    indicators = IndicatorsRepository()
    marketdata = MarketDataRepository()

    start_date = date(2025, 1,1)
    end_date = date(2025, 1, 18)

    working_date = start_date
    starting_capital = 100000
    risk_tolerance = 1
    sl_multiplier = 2

    while working_date <= end_date:
        if working_date.weekday() < 5:
            top10 = ranking.get_top_n_rankings_by_date(10, working_date)
            if not top10:
                print(f"No rankings found for {working_date}")
                working_date += timedelta(days=1)
                continue

            if start_date==working_date:
                current_capital = starting_capital
                stock_risk = current_capital * risk_tolerance / 100
                working_capital = current_capital
                invested_data = []
                for item in top10:
                    data = {}
                    atr = round(indicators.get_indicator_by_tradingsymbol('atrr_14', item.tradingsymbol, working_date),2)
                    closing_price = marketdata.get_marketdata_by_trading_symbol(item.tradingsymbol, working_date).close
                    stoploss = round(closing_price - sl_multiplier*atr,2)
                    units = math.floor(stock_risk / (sl_multiplier*atr))
                    capital_needed = round(closing_price * units,2)
                    if working_capital >= capital_needed:
                        working_capital -= capital_needed
                        working_capital = round(working_capital,2)
                        break_flag = False
                    else:
                        units = math.floor(working_capital / closing_price)
                        capital_needed = round(closing_price * units, 2)
                        working_capital -= capital_needed
                        working_capital = round(working_capital,2)
                        break_flag = True

                    data = {
                        'tradingsymbol' : item.tradingsymbol,
                        'working_date' : working_date,
                        'entry_price' : closing_price,
                        'score' : item.composite_score,
                        'atr' : atr,
                        'entry_sl' : stoploss,
                        'units' : units,
                        'risk' : round(units * (closing_price - stoploss),2),
                        'capital_needed' : capital_needed,
                        'working_capital' : working_capital,
                        'current_price' : closing_price,
                        'current_sl' : stoploss
                    }

                    invested_data.append(data)
                    if break_flag:
                        break
                df = pd.DataFrame(invested_data)
                print(df)
        working_date += timedelta(days=1)

    return 'successful'

if __name__ == "__main__":
    app.run(debug=True)