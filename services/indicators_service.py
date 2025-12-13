import pandas as pd
import pandas_ta as ta
from config.app_config import CONFIG

class IndicatorsService:
    def __init__(self, market_data, db_manager):
        self.market_data = market_data
        self.db_manager = db_manager

    def ema(self, ticker, length, column_name="close"):
        df = self.market_data[ticker]
        return df.ta.ema(close=column_name, length=length)

    def rsi(self, ticker, length, smooth_length, column_name='Close'):
        df = self.market_data[ticker]
        rsi = df.ta.rsi(close=column_name, length=length)
        rsi_smooth = self.ema(ticker, smooth_length, column_name='RSI')
        return rsi, rsi_smooth

    def roc(self, ticker, length, column_name="close"):
        df = self.market_data[ticker]
        return df.ta.roc(close=column_name, length=length)

    def stoch(self, ticker, k_period, d_period, column_names=("High", "Low", "Close")):
        df = self.market_data[ticker]
        stoch = df.ta.stoch(high=column_names[0], low=column_names[1], close=column_names[2], k=k_period, d=d_period)
        return stoch[stoch.columns[0]], stoch[stoch.columns[1]]

    def macd(self, ticker, fast, slow, signal, column_name="close"):
        df = self.market_data[ticker]
        macd = df.ta.macd(close=column_name, fast=fast, slow=slow, signal=signal)
        return macd[macd.columns[0]], macd[macd.columns[2]]

    def bollinger_bands(self, ticker, window, std, column_name="close"):
        df = self.market_data[ticker]
        bbands = df.ta.bbands(close=column_name, length=window, std=std)
        return (bbands[bbands.columns[0]],
                bbands[bbands.columns[2]],
                bbands[bbands.columns[1]],
                bbands[bbands.columns[3]]
        )

    def min_lookback(self, df, lookback_days):
        return df.rolling(window=lookback_days).min()

    def max_lookback(self, df, lookback_days):
        return df.rolling(window=lookback_days).max()
