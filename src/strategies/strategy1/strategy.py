from datetime import date, timedelta
import math
import pandas as pd

from repositories import RankingRepository
from repositories import IndicatorsRepository
from repositories import MarketDataRepository
from repositories import HoldingsRepository

ranking = RankingRepository()
indicators = IndicatorsRepository()
marketdata = MarketDataRepository()
holdings = HoldingsRepository()

class Strategy:
    @staticmethod
    def backtesting(start_date, end_date, parameters):
        working_date = start_date
        while working_date <= end_date:
            if working_date.weekday() < 5:
                top_n = ranking.get_top_n_rankings_by_date(parameters.max_positions, working_date)
                if not top_n:
                    print(f"No rankings found for {working_date}")
                    working_date += timedelta(days=1)
                    continue

                summary = {'date': working_date}

                if start_date==working_date:
                    current_capital = parameters.initial_capital  #only valid for day1
                    stock_risk = current_capital * parameters.risk_threshold / 100 # has to be calculated every time capital is changed or based on initial capital only ?
                    working_capital = current_capital #only valid for day1

                    summary['sold'] = 0
                    summary['initial_capital'] = current_capital
                    summary['working_capital'] = current_capital

                    invested_data = []
                    bought = 0
                    capital_risk = 0
                    portfolio_value = 0
                    portfolio_risk = 0
                    for item in top_n:
                        data = {}
                        atr = round(indicators.get_indicator_by_tradingsymbol('atrr_14', item.tradingsymbol, working_date),2)
                        closing_price = marketdata.get_marketdata_by_trading_symbol(item.tradingsymbol, working_date).close

                        risk_per_trade = round(parameters.sl_multiplier*atr)
                        stoploss = round(closing_price - risk_per_trade,2)
                        units = math.floor(stock_risk / risk_per_trade)
                        capital_needed = round(closing_price * units,2)

                        if working_capital >= capital_needed:
                            working_capital -= capital_needed
                            working_capital = round(working_capital,2)

                        else:
                            units = math.floor(working_capital / closing_price)
                            capital_needed = round(closing_price * units, 2)
                            working_capital -= capital_needed
                            working_capital = round(working_capital,2)


                        data = {
                            'tradingsymbol' : item.tradingsymbol,
                            'working_date' : working_date,
                            'entry_date' : working_date,
                            'entry_price' : closing_price,
                            'score' : round(item.composite_score,2),
                            'atr' : atr,
                            'entry_sl' : stoploss,
                            'units' : units,
                            'risk' : round(units * risk_per_trade,2),
                            'capital_needed' : capital_needed,
                            'working_capital' : working_capital,
                            'current_price' : closing_price,
                            'current_sl' : stoploss
                        }
                        if units > 0:
                            invested_data.append(data)
                            bought += data['capital_needed']
                            capital_risk += (data['units'] * (data['entry_price'] - data['current_sl']))
                            portfolio_value += (data['units'] * data['current_price'])
                            portfolio_risk += (data['units'] * (data['current_price'] - data['current_sl']))

                    holdings.delete_holdings_by_date(working_date)
                    holdings.bulk_insert(invested_data)
                    summary['bought'] = bought
                    summary['capital_risk'] = capital_risk
                    summary['portfolio_value'] = round(portfolio_value,2)
                    summary['portfolio_risk'] = portfolio_risk
                    summary['remaining_capital'] = round(summary['working_capital'] - summary['bought'],2)

                else:
                    # check sl of already invested, sell one's that have hit SL
                    # check score of remaining invested, sell one's which have score below 40
                    # check how many remaining invested  part of current top10
                    # identify the swap's if any, sell one's to be swapped (from lowest current score of invested, check from top of new top10's univested if score more than % threshold)
                    # identify new working working capital : remaining cap from prev week (incorporate ways to capture new infused capital)
                    # buy new stocks upto capital / max positions limit
                    # update


                    print(working_date)
                    break
            working_date += timedelta(days=1)


    @staticmethod
    def add_holding(symbol, working_capital, stock_risk, parameters, working_date):
        atr = round(indicators.get_indicator_by_tradingsymbol('atrr_14', symbol, working_date),2)
        closing_price = marketdata.get_marketdata_by_trading_symbol(symbol, working_date).close

        risk_per_trade = round(parameters.sl_multiplier*atr)
        stoploss = round(closing_price - risk_per_trade,2)
        units = math.floor(stock_risk / risk_per_trade)
        capital_needed = round(closing_price * units,2)

        if working_capital >= capital_needed:
            working_capital -= capital_needed
            working_capital = round(working_capital,2)

        else:
            units = math.floor(working_capital / closing_price)
            capital_needed = round(closing_price * units, 2)
            working_capital -= capital_needed
            working_capital = round(working_capital,2)

        stock_data = {
            'tradingsymbol' : symbol,
            'working_date' : working_date,
            'entry_date' : working_date,
            'entry_price' : closing_price,
            'atr' : atr,
            'entry_sl' : stoploss,
            'units' : units,
            'risk' : round(units * risk_per_trade,2),
            'capital_needed' : capital_needed,
            'working_capital' : working_capital,
            'current_price' : closing_price,
            'current_sl' : stoploss
        }

        return stock_data


    @staticmethod
    def sell_holding(symbol, units, selling_price, working_capital):
        sold_value = round(units * selling_price,2)
        working_capital += sold_value


    

