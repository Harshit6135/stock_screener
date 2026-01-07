from datetime import date, timedelta
import math
import pandas as pd

from repositories import RankingRepository
from repositories import IndicatorsRepository
from repositories import MarketDataRepository
from repositories import HoldingsRepository
from repositories import ActionsRepository
from repositories import InvestmentRepository
from config import setup_logger

logger = setup_logger(name="Strategy1")

ranking = RankingRepository()
indicators = IndicatorsRepository()
marketdata = MarketDataRepository()
holdings = HoldingsRepository()
actions = ActionsRepository()
investment = InvestmentRepository()

class Strategy:
    @staticmethod
    def provide_actions(working_date, parameters):
        pending_actions = investment.check_pending_actions(working_date)
        if pending_actions:
            return 'Actions pending from another date, please take action before proceeding'

        top_n = ranking.get_top_n_by_date(parameters.max_positions, working_date)
        current_holdings = investment.get_holdings()
        new_actions = []
        if not current_holdings:
            for item in top_n:
                action = Strategy.buy_action(item.tradingsymbol, working_date, parameters, 'top 10 buys')
                new_actions.append(action)
            investment.bulk_insert_actions(new_actions)
            # investment.insert_summary({'working_date' : working_date,
            #                            'starting_capital' : 100000,
            #                            'sold' : 10000.562,
            #                            'bought' : 20000.562,
            #                            'capital_risk' : 30000.562,
            #                            'portfolio_value' : 24562,
            #                            'portfolio_risk' : 1203.684,
            #                            'net_pnl' : 653.8954,
            #                            'pnl_percentage' : 25.569})
        else:
            # check for stoploss and sell
            i=0
            while i<=len(current_holdings):
                low = Strategy.fetch_low(current_holdings[i].symbol, working_date)
                if current_holdings[i].current_sl >= low:
                    action = Strategy.sell_action(current_holdings[i].symbol, working_date, current_holdings[i].units, 'stoploss')
                    new_actions.append(action)
                    current_holdings.pop(i)
                else:
                    i+=1

            # check for current_holdings in top_n
            i = 0
            while i < len(current_holdings):
                j=0
                while j < len(top_n):
                    if top_n[j].tradingsymbol == current_holdings[i].tradingsymbol:
                        top_n.pop(j)
                        break
                    else:
                        j+=1
                i+=1

            # buy for the remaining positions
            remaining_buys = parameters.max_positions-len(current_holdings)
            i=0
            while i < remaining_buys:
                action = Strategy.buy_action(top_n[i].tradingsymbol, working_date, parameters, 'top 10 buys')
                new_actions.append(action)
                i+=1

            # check for swaps


        return 'Actions Generated'


    @staticmethod
    def backtesting(start_date, end_date, parameters):
        working_date = start_date
        holdings.delete_holdings_all()
        holdings.delete_summary_all()
        actions.delete_actions_all()

        while working_date <= end_date:
            if working_date.weekday() == 4:
                top_n = ranking.get_top_n_by_date(parameters.max_positions, working_date)
                if not top_n:
                    logger.warning(f"No rankings found for {working_date}")
                    working_date += timedelta(days=1)
                    continue

                actions.delete_actions(working_date)
                if start_date==working_date:
                    current_capital = parameters.initial_capital  #only valid for day1
                    stock_risk = current_capital * parameters.risk_threshold / 100 # has to be calculated every time capital is changed or based on initial capital only ?
                    working_capital = current_capital #only valid for day1

                    week_holdings = []

                    for item in top_n:
                        entry_price = marketdata.get_marketdata_next_day(item.tradingsymbol, working_date).open

                        buy_holding_parameters = {
                            'symbol' : item.tradingsymbol,
                            'working_capital' : working_capital,
                            'stock_risk' : stock_risk,
                            'parameters' : parameters,
                            'working_date' : working_date,
                            'entry_price' : entry_price,
                            'score' : round(item.composite_score,2)
                        }

                        stock_data = Strategy.buy_holding(**buy_holding_parameters)

                        working_capital = stock_data['working_capital']
                        if stock_data['units'] >0:
                            week_holdings.append(stock_data)

                    summary_parameters = {
                        'starting_capital' : current_capital,
                        'sold' : 0,
                        'remaining_capital' : working_capital
                    }

                    holdings.bulk_insert(week_holdings)
                    summary = Strategy.get_summary(week_holdings, **summary_parameters)
                    holdings.insert_summary(summary)

                # if working_date != start_date
                else:
                    logger.info(f"Processing date: {working_date}")
                    sold = 0
                    current_holdings = holdings.get_holdings()
                    prev_summary = holdings.get_summary()

                    current_capital = prev_summary.remaining_capital
                    working_capital = current_capital

                    stock_risk = (current_capital + prev_summary.portfolio_value) * parameters.risk_threshold / 100
                    week_holdings = []

                    # check for stoploss and sell
                    for item in current_holdings:
                        low = Strategy.fetch_low(item.tradingsymbol, working_date)
                        if item.current_sl >= low:
                            # logger.info(f'Selling {item.tradingsymbol} as below SL')
                            selling_price = item.current_sl
                            sold += item.units * selling_price
                            sell_parameters = {
                                'symbol' : item.tradingsymbol,
                                'units' : item.units,
                                'selling_price' : selling_price,
                                'working_capital' : working_capital,
                                'working_date' : working_date,
                                'sell_reason' : 'stoploss'
                            }

                            working_capital = Strategy.sell_holding(**sell_parameters)
                            current_holdings.remove(item)

                    # check for current_holdings in top_n
                    i = 0
                    while i < len(current_holdings):
                        j=0
                        while j < len(top_n):
                            if top_n[j].tradingsymbol == current_holdings[i].tradingsymbol:
                                # logger.debug(f'{top_n[j].tradingsymbol} already part of invested')
                                top_n.pop(j)
                                break
                            else:
                                j+=1
                        i+=1
                    # buy for the remaining positions
                    remaining_buys = parameters.max_positions-len(current_holdings)
                    logger.info(f'Remaining buys {remaining_buys}')
                    i=0
                    while i < remaining_buys:
                        entry_price = marketdata.get_marketdata_next_day(top_n[i].tradingsymbol, working_date).open
                        buy_holding_parameters = {
                            'symbol' : top_n[i].tradingsymbol,
                            'working_capital' : working_capital,
                            'stock_risk' : stock_risk,
                            'parameters' : parameters,
                            'working_date' : working_date,
                            'entry_price' : entry_price,
                            'score' : round(top_n[i].composite_score,2)
                        }
                        logger.info(f'Buying {top_n[i].tradingsymbol}')
                        stock_data = Strategy.buy_holding(**buy_holding_parameters)
                        working_capital = stock_data['working_capital']
                        if stock_data['units'] >0:
                            week_holdings.append(stock_data)
                        i+=1

                    i=0
                    while i < len(week_holdings):
                        j=0
                        while j < len(top_n):
                            if top_n[j].tradingsymbol == week_holdings[i]['tradingsymbol']:
                                logger.debug(f'Skipping {top_n[j].tradingsymbol} as already bought')
                                top_n.pop(j)
                                break
                            else:
                                j+=1
                        i+=1

                    logger.info(f'Remaining {len(top_n)} stocks to check from top_n')

                    # check for swaps
                    i = 0
                    while i < len(top_n):
                        buy_flag = False
                        j=0
                        while j < len(current_holdings):
                            current_score = ranking.get_by_symbol(current_holdings[j].tradingsymbol, working_date).composite_score
                            
                            if top_n[i].composite_score > (1 + (parameters.buffer_percent/100))*current_score:
                                logger.info(f'Selling {current_holdings[j].tradingsymbol} and buying {top_n[i].tradingsymbol}')
                                # sell current_holdings[j]
                                selling_price = marketdata.get_marketdata_next_day(current_holdings[j].tradingsymbol, working_date).open
                                sold += current_holdings[j].units * selling_price

                                sell_parameters = {
                                    'symbol' : current_holdings[j].tradingsymbol,
                                    'units' : current_holdings[j].units,
                                    'selling_price' : selling_price,
                                    'working_capital' : working_capital,
                                    'working_date' : working_date,
                                    'sell_reason' : f'swap with {top_n[i].tradingsymbol}'
                                }
                                working_capital = Strategy.sell_holding(**sell_parameters)
                                current_holdings.pop(j)

                                # buy top_n[i]
                                entry_price = marketdata.get_marketdata_next_day(top_n[i].tradingsymbol, working_date).open
                                buy_holding_parameters = {
                                    'symbol' : top_n[i].tradingsymbol,
                                    'working_capital' : working_capital,
                                    'stock_risk' : stock_risk,
                                    'parameters' : parameters,
                                    'working_date' : working_date,
                                    'entry_price' : entry_price,
                                    'score' : round(top_n[i].composite_score,2)
                                }

                                stock_data = Strategy.buy_holding(**buy_holding_parameters)
                                working_capital = stock_data['working_capital']
                                if stock_data['units'] >0:
                                    week_holdings.append(stock_data)
                                buy_flag = True
                                break
                            else:
                                j+=1
                        if buy_flag:
                            top_n.pop(i)
                        else:
                            i+=1

                    # update current holdings with recent data
                    for item in current_holdings:
                        stock_data = item.to_dict()
                        stock_data['working_date'] = working_date
                        stock_data['atr'] = round(indicators.get_indicator_by_tradingsymbol('atrr_14', item.tradingsymbol, working_date),2)
                        stock_data['score'] = round(ranking.get_by_symbol(item.tradingsymbol, working_date).composite_score,2)
                        stock_data['current_price'] = marketdata.get_marketdata_by_trading_symbol(item.tradingsymbol, working_date).close
                        current_sl = stock_data['current_price'] - (stock_data['atr']*parameters.sl_multiplier)
                        if current_sl > stock_data['current_sl']:
                            stock_data['current_sl'] = current_sl
                        stock_data['risk'] = stock_data['units'] * (stock_data['entry_price'] - stock_data['current_sl'])
                        if stock_data['risk']<=0:
                            stock_data['risk'] = 0

                        week_holdings.append(stock_data)
                    holdings.bulk_insert(week_holdings)

                    summary_parameters = {
                        'starting_capital' : prev_summary.remaining_capital,
                        'sold' : sold,
                        'remaining_capital' : working_capital
                    }

                    summary = Strategy.get_summary(week_holdings, **summary_parameters)
                    holdings.insert_summary(summary)

            working_date += timedelta(days=1)


    @staticmethod
    def buy_holding(symbol, working_capital, stock_risk, parameters, working_date, entry_price, score):
        atr = round(indicators.get_indicator_by_tradingsymbol('atrr_14', symbol, working_date),2)

        if atr==0:
            logger.warning(f'O ATR in the data for {symbol} on {working_date}')
        risk_per_trade = round(parameters.sl_multiplier*atr,2)
        if risk_per_trade==0:
            logger.warning(f'0 Risk Per Trade for {symbol} on {working_date}. ATR {atr}')

        stoploss = round(entry_price - risk_per_trade,2)
        units = math.floor(stock_risk / risk_per_trade)
        capital_needed = round(entry_price * units,2)

        if working_capital >= capital_needed:
            working_capital -= capital_needed
            working_capital = round(working_capital,2)
        else:
            units = math.floor(working_capital / entry_price)
            capital_needed = round(entry_price * units, 2)
            working_capital -= capital_needed
            working_capital = round(working_capital,2)

        stock_data = {
            'tradingsymbol' : symbol,
            'working_date' : working_date,
            'entry_date' : working_date,
            'entry_price' : entry_price,
            'atr' : atr,
            'entry_sl' : stoploss,
            'units' : units,
            'score' : score,
            'risk' : round(units * risk_per_trade,2),
            'capital_needed' : capital_needed,
            'working_capital' : working_capital,
            'current_price' : entry_price,
            'current_sl' : stoploss
        }

        action_data = {
            'action_date': working_date,
            'action_type': 'buy',
            'tradingsymbol': symbol,
            'units': units,
            'price': entry_price
        }
        actions.add(action_data)
        return stock_data


    @staticmethod
    def sell_holding(symbol, units, selling_price, working_capital, working_date, sell_reason):
        sold_value = round(units * selling_price,2)
        working_capital += sold_value
        working_capital = round(working_capital,2)

        action_data = {
            'action_date': working_date,
            'action_type': 'sell',
            'tradingsymbol': symbol,
            'units': units,
            'price': selling_price,
            'reason' : sell_reason
        }
        actions.add(action_data)
        return working_capital


    @staticmethod
    def get_summary(week_holdings, starting_capital, sold, remaining_capital):
        # Convert list of holdings to DataFrame for fast/vectorized calculations
        df = pd.DataFrame(week_holdings)

        # Bought: sum(entry_price * units) where entry_date == working_date
        bought_mask = df['entry_date'] == df['working_date']
        bought = (df.loc[bought_mask, 'entry_price'] * df.loc[bought_mask, 'units']).sum()

        # Capital risk: sum(units * (entry_price - current_sl))
        capital_risk = (df['units'] * (df['entry_price'] - df['current_sl'])).sum()

        # Portfolio value: sum(units * current_price)
        portfolio_value = (df['units'] * df['current_price']).sum()

        # Portfolio risk: sum(units * (current_price - current_sl))
        portfolio_risk = (df['units'] * (df['current_price'] - df['current_sl'])).sum()

        # Prepare summary with rounded numbers
        summary = {
            'working_date': week_holdings[0]['working_date'],
            'starting_capital': round(starting_capital, 2),
            'sold': round(sold, 2),
            'working_capital': round(starting_capital + sold, 2),
            'bought': round(float(bought), 2),
            'capital_risk': round(float(capital_risk), 2),
            'portfolio_value': round(float(portfolio_value), 2),
            'remaining_capital': round(float(remaining_capital), 2),
            'portfolio_risk': round(float(portfolio_risk), 2)
        }
        return summary


    @staticmethod
    def fetch_low(symbol, working_date):
        filter_data = {
            'tradingsymbol' : symbol,
            'start_date' : working_date - timedelta(days=6),
            'end_date' : working_date
        }
        weekly_data = marketdata.query(filter_data)
        low = 0
        for item in weekly_data:
            if low==0:
                low = item.low
            elif item.low < low:
                low = item.low
        return low


    @staticmethod
    def buy_action(symbol, working_date, parameters, reason):
        atr = round(indicators.get_indicator_by_tradingsymbol('atrr_14', symbol, working_date),2)
        closing_price = marketdata.get_marketdata_by_trading_symbol(symbol, working_date).close
        risk_per_unit = parameters.sl_multiplier*atr

        summary = investment.get_summary()

        if not summary:
            capital = parameters.initial_capital
        else:
            capital = summary.portfolio_value + summary.remaining_capital

        max_risk = capital * parameters.risk_threshold / 100
        units = math.floor(max_risk / risk_per_unit)

        capital_needed = units * closing_price

        action = {
            'working_date' : working_date,
            'type' : 'buy',
            'reason' : reason,
            'symbol' : symbol,
            'risk' : risk_per_unit,
            'atr' : atr,
            'units' : units,
            'prev_close' : closing_price,
            'capital' : capital_needed
        }

        return action


    @staticmethod
    def sell_action(symbol, working_date, units, reason):
        closing_price = marketdata.get_marketdata_by_trading_symbol(symbol, working_date).close

        capital_available = units * closing_price
        action = {
            'working_date' : working_date,
            'type' : 'sell',
            'reason' : reason,
            'symbol' : symbol,
            'units' : units,
            'prev_close' : closing_price,
            'capital' : capital_available
        }

        return action