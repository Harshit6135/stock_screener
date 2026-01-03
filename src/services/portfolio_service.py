from datetime import date

from utils import calculate_initial_stop_loss, calculate_effective_stop
from repositories import (ConfigRepository, PortfolioRepository,
                          MarketDataRepository, IndicatorsRepository,
                          InstrumentsRepository, RankingRepository, ScoreRepository)

config_repo = ConfigRepository()
portfolio_repo = PortfolioRepository()
marketdata_repo = MarketDataRepository()
indicators_repo = IndicatorsRepository()
instr_repo = InstrumentsRepository()
rank_repo = RankingRepository()
score_repo = ScoreRepository()


class PortfolioService:
    """Service for portfolio management and action generation"""
    
    def __init__(self):
        """
        Initialize with risk configuration.
        """
        self.config = config_repo.get_config()

    def generate_portfolio_summary(self):
        invested = portfolio_repo.get_invested()

        total_investment = 0.0
        current_value = 0.0

        for i in invested:
            investment_amount = i.buy_price * i.num_shares
            total_investment += investment_amount

            latest_data = marketdata_repo.get_latest_date_by_symbol(i.tradingsymbol)
            price = latest_data.close if latest_data else i.buy_price
            current_value += price * i.num_shares

        capital_left = (self.config.current_capital - total_investment) if self.config else 0.0
        absolute_return = current_value - total_investment

        return {
            "total_investment": round(total_investment, 2),
            "total_stocks": len(invested),
            "capital_left": round(capital_left, 2),
            "current_value": round(current_value, 2),
            "absolute_return": round(absolute_return, 2)
        }

    def add_new_stock(self, invest_data):
        symbol = invest_data['tradingsymbol']
        buy_price = invest_data['buy_price']
        num_shares = invest_data['num_shares']
        buy_date = invest_data.get('buy_date') or date.today()
        
        # Capture original inputs for capital calculation
        input_buy_price = invest_data['buy_price']
        input_num_shares = invest_data['num_shares']

        # Check if already invested
        existing = portfolio_repo.get_invested_by_symbol(symbol)
        
        # 1. Fetch Instrument Details
        instrument = instr_repo.get_by_symbol(symbol)
        instrument_token = instrument.instrument_token if instrument else None
        exchange = instrument.exchange if instrument else 'NSE'

        # 2. Fetch ATR for the buy date (or latest prior)
        atr = indicators_repo.get_indicator_by_tradingsymbol("atrr_14", symbol,  date=buy_date)
        score = score_repo.get_by_symbol(symbol)
        current_score = score.composite_score if score else None

        # 3. Calculate Stop Loss
        stop_multiplier = self.config.stop_loss_multiplier if self.config else 3.0
        # Use fallback ATR of 3% if missing, to prevent calculation errors
        used_atr = atr if atr else (buy_price * 0.03) 
        initial_stop = calculate_initial_stop_loss(buy_price, used_atr, stop_multiplier)
        current_stop = initial_stop

        # 4. If backdated trade, calculate current stop loss based on latest data
        # Note: If merging, we might override this below.
        if buy_date < date.today():
             latest_market = marketdata_repo.get_latest_date_by_symbol(symbol)
             latest_atr = indicators_repo.get_indicator_by_tradingsymbol("atrr_14", symbol) # latest
             
             if latest_market and latest_atr:
                 current_price = latest_market.close
                 # Use effective stop logic: trails up
                 sl_response = calculate_effective_stop(
                     buy_price=buy_price,
                     current_price=current_price,
                     current_atr=latest_atr,
                     initial_stop=initial_stop,
                     stop_multiplier=stop_multiplier,
                     sl_step_percent=0.10 
                 )
                 current_stop = sl_response['effective_stop']

        # Handle averaging if already invested
        if existing:
            total_shares = num_shares + existing.num_shares
            # Weighted average price
            new_avg_price = (buy_price * num_shares + existing.num_shares * existing.buy_price) / total_shares
            
            # Update existing record
            existing.num_shares = total_shares
            existing.buy_price = new_avg_price
            existing.buy_date = buy_date # Move to latest entry date
            existing.initial_stop_loss = round(initial_stop, 2) # Reset initial stop to this new entry's stop
            
            # Update current stop loss: Move it UP if the new calculation (based on today/latest) is higher.
            # This handles both "Pyramiding" (adding to winners) and "Backdated Logic" (price moved up).
            existing.current_stop_loss = max(existing.current_stop_loss, round(current_stop, 2))
            
            existing.atr_at_entry = atr
            existing.current_score = current_score
            existing.include_in_strategy = invest_data.get('include_in_strategy', True)
            
            invested = portfolio_repo.update_stock(existing)
            
            
            # Update Capital (Only for the NEW shares) - REMOVED
            # Treating current_capital as Total Equity now.
            # if self.config:
            #     cost = input_buy_price * input_num_shares
            #     new_capital = self.config.current_capital - cost
            #     config_repo.update_config({"current_capital": new_capital})

            return invested

        final_data = {
            "tradingsymbol": symbol,
            "instrument_token": instrument_token,
            "exchange": exchange,
            "buy_price": buy_price,
            "num_shares": num_shares,
            "buy_date": buy_date,
            "atr_at_entry": atr,
            "initial_stop_loss": round(initial_stop, 2),
            "current_stop_loss": round(current_stop, 2),
            "current_score": current_score,
            "include_in_strategy": invest_data.get('include_in_strategy', True)
        }
        invested = portfolio_repo.buy_stock(final_data)
        
        # Update Capital - REMOVED
        # Treating current_capital as Total Equity.
        # if self.config:
        #     cost = buy_price * num_shares
        #     new_capital = self.config.current_capital - cost
        #     config_repo.update_config({"current_capital": new_capital})
            
        return invested
        
    def sell_stock(self, sell_data):
        symbol = sell_data['tradingsymbol']
        sell_price = sell_data['sell_price']
        sell_units = sell_data['num_shares']
        # sell_date = sell_data.get('sell_date') # For logging, but we don't store transactions yet
        
        existing = portfolio_repo.get_invested_by_symbol(symbol)
        if not existing:
             raise Exception("Not invested in this stock")
             
        if sell_units > existing.num_shares:
             raise Exception(f"Cannot sell {sell_units} units. Only {existing.num_shares} held.")
             
        # Calculate PnL to update Total Equity (Current Capital)
        pnl = (sell_price - existing.buy_price) * sell_units
        if self.config:
            new_capital = self.config.current_capital + pnl
            config_repo.update_config({"current_capital": new_capital})
            
        # Update Shares
        existing.num_shares -= sell_units
        
        if existing.num_shares == 0:
            portfolio_repo.delete_stock(symbol)
            return {"message": "Position closed", "remaining_shares": 0}
        else:
            # Refresh Rank/Score for remaining (from avg_score)
            score = score_repo.get_by_symbol(symbol)
            if score:
                existing.current_score = score.composite_score
            
            portfolio_repo.update_stock(existing)
            return {"message": "Position reduced", "remaining_shares": existing.num_shares}

    def get_invested_stocks(self):
        """Get all invested stocks enriched with current score from avg_score"""
        invested = portfolio_repo.get_invested()

        # Enrich with Score from avg_score table
        for inv in invested:
            score = score_repo.get_by_symbol(inv.tradingsymbol)
            if score:
                inv.current_score = score.composite_score
            else:
                inv.rank = None
        
        return invested

