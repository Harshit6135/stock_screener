import pandas as pd
import pandas_ta as ta
from config.app_config import CONFIG

class AnalysisService:
    def __init__(self, market_data, db_manager):
        self.market_data = market_data
        self.db_manager = db_manager

    def analyze_stock(self, ticker):
        try:
            df = self.market_data[ticker]

            if df.empty or len(df) < CONFIG["trend"]["long_ma"]:
                return {
                    "Symbol": ticker,
                    "Data_Found": False,
                    "Issue": "Insufficient Data"
                }


            # EMAs
            short_ma = CONFIG["trend"]["short_ma"]
            long_ma = CONFIG["trend"]["long_ma"]
            df['Short_MA'] = df.ta.ema(close='Close', length=short_ma)
            df['Long_MA'] = df.ta.ema(close='Close', length=long_ma)

            # RSI
            rsi_n = CONFIG["momentum"]["rsi_period"]
            df['RSI'] = df.ta.rsi(close='Close', length=rsi_n)
            # RSI Signal is not a standard output of ta.rsi, so we calculate it manually or using ma
            # User Change: RSI Smoothened over 3 day EMA
            rsi_smooth = CONFIG['momentum']['rsi_smooth']
            df['RSI_Signal'] = df.ta.ema(close='RSI', length=rsi_smooth)

            # ROC
            n = CONFIG['momentum']['roc_period']
            df['ROC'] = df.ta.roc(close='Close', length=n)

            # Stochastics
            k_period = CONFIG['stochastic']['k_period']
            d_period = CONFIG['stochastic']['d_period']
            # pandas_tastoch returns a DataFrame with columns like STOCHk_14_3_3, STOCHd_14_3_3
            stoch = df.ta.stoch(high='High', low='Low', close='Close', k=k_period, d=d_period)
            # We need to map dynamic column names or access by index/suffix
            # Assuming standard naming convention from pandas_ta
            # Usually column names are formatted: STOCHk_{k}_{d}_{smooth_k}, STOCHd_{k}_{d}_{smooth_k}
            # To be safe, we can inspect columns or just assign by order if deterministic, but safer to use simple column mapping
            # Let's try to match the columns by looking for 'STOCHk' and 'STOCHd'
            df['Stoch_K'] = stoch[stoch.columns[0]] 
            df['Stoch_D'] = stoch[stoch.columns[1]]

            # MACD
            fast = CONFIG["gps"]["fast"]
            slow = CONFIG["gps"]["slow"]
            sig = CONFIG["gps"]["signal"]
            macd = df.ta.macd(close='Close', fast=fast, slow=slow, signal=sig)
            # MACD returns MACD, MACDh (histogram), MACDs (signal)
            # Column names like MACD_12_26_9, MACDh_..., MACDs_...
            # The order in returning DF is MACD line, Histogram, Signal line
            df['MACD'] = macd[macd.columns[0]]
            df['Signal_Line'] = macd[macd.columns[2]] # Index 2 is signal line usually (check docs or verify)
            # Actually pandas_ta returns: MACD, MACDh, MACDs. 
            # 0: MACD line
            # 1: Histogram
            # 2: Signal line

            # Bollinger Bands
            bb_n = CONFIG["squeeze"]["bb_window"]
            bb_std = CONFIG["squeeze"]["bb_std"]
            bbands = df.ta.bbands(close='Close', length=bb_n, std=bb_std)
            # Returns BBL, BBM, BBU, BBB, BBP
            # BBL: Lower, BBM: Middle, BBU: Upper
            df['BB_Upper'] = bbands[bbands.columns[2]] # BBU
            df['BB_Lower'] = bbands[bbands.columns[0]] # BBL
            df['SMA_BB'] = bbands[bbands.columns[1]]   # BBM
            
            # Bandwidth: ((Upper - Lower) / Middle) * 100
            # pandas_ta calculates BBB which is Bandwidth
            df['Bandwidth'] = bbands[bbands.columns[3]]

            lookback = CONFIG["squeeze"]["lookback_days"]
            df['Hist_Low_BW'] = df['Bandwidth'].rolling(window=lookback).min()

            # Volume Indicators
            v_short = CONFIG["volume"]["short_ema"]
            v_long = CONFIG["volume"]["long_ema"]
            df['Vol_Short'] = df.ta.ema(close='Volume', length=v_short)
            df['Vol_Long'] = df.ta.ema(close='Volume', length=v_long)

            latest = df.iloc[-1]
            
            result = {
                "Symbol": ticker,
                "Data_Found": True,
                "Price": round(latest['Close'].item(), 2),
                "Short_MA": round(latest['Short_MA'].item(), 2),
                "Long_MA": round(latest['Long_MA'].item(), 2),
                "RSI": round(latest['RSI'].item(), 2),
                "RSI_Signal": round(latest['RSI_Signal'].item(), 2),
                "ROC": round(latest['ROC'].item(), 2),
                "MACD": round(latest['MACD'].item(), 2),
                "Signal_Line": round(latest['Signal_Line'].item(), 2),
                "Stoch_K": round(latest['Stoch_K'].item(), 2),
                "Stoch_D": round(latest['Stoch_D'].item(), 2),
                "Bandwidth": round(latest['Bandwidth'].item(), 2),
                "Hist_Low_BW": round(latest['Hist_Low_BW'], 2),
                "Volume": latest['Volume'].item(),
                "Vol_Short": latest['Vol_Short'],
                "Vol_Long": latest['Vol_Long']
            }
            
            # Save latest indicators to DB
            self.db_manager.save_indicators(ticker, result)
            
            return result

        except Exception as e:
            return {
                "Symbol": ticker,
                "Data_Found": False,
                "Issue": str(e)
            }
