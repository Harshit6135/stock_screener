import pandas as pd
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
            df['Short_MA'] = df['Close'].ewm(span=short_ma, adjust=False).mean()
            df['Long_MA'] = df['Close'].ewm(span=long_ma, adjust=False).mean()

            # RSI
            rsi_n = CONFIG["momentum"]["rsi_period"]
            delta = df['Close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=rsi_n).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=rsi_n).mean()
            rs = gain / loss
            df['RSI'] = 100 - (100 / (1 + rs))
            df['RSI_Signal'] = df['RSI'].rolling(window=CONFIG['momentum']['rsi_smooth']).mean()

            # ROC
            n = CONFIG['momentum']['roc_period']
            df['ROC'] = df['Close'].pct_change(periods=n) * 100

            # Stochastics
            low_min = df['Low'].rolling(window=CONFIG['stochastic']['k_period']).min()
            high_max = df['High'].rolling(window=CONFIG['stochastic']['k_period']).max()
            df['Stoch_K'] = 100 * ((df['Close'] - low_min) / (high_max - low_min))
            df['Stoch_D'] = df['Stoch_K'].rolling(window=CONFIG['stochastic']['d_period']).mean()

            # MACD
            fast = CONFIG["gps"]["fast"]
            slow = CONFIG["gps"]["slow"]
            sig = CONFIG["gps"]["signal"]
            df['EMA_Fast'] = df['Close'].ewm(span=fast, adjust=False).mean()
            df['EMA_Slow'] = df['Close'].ewm(span=slow, adjust=False).mean()
            df['MACD'] = df['EMA_Fast'] - df['EMA_Slow']
            df['Signal_Line'] = df['MACD'].ewm(span=sig, adjust=False).mean()

            # Bollinger Bands
            bb_n = CONFIG["squeeze"]["bb_window"]
            bb_std = CONFIG["squeeze"]["bb_std"]
            df['SMA_BB'] = df['Close'].rolling(window=bb_n).mean()
            df['Std_Dev'] = df['Close'].rolling(window=bb_n).std()
            df['BB_Upper'] = df['SMA_BB'] + (df['Std_Dev'] * bb_std)
            df['BB_Lower'] = df['SMA_BB'] - (df['Std_Dev'] * bb_std)
            df['Bandwidth'] = ((df['BB_Upper'] - df['BB_Lower']) / df['SMA_BB']) * 100

            lookback = CONFIG["squeeze"]["lookback_days"]
            df['Hist_Low_BW'] = df['Bandwidth'].rolling(window=lookback).min()

            # Volume Indicators
            v_short = CONFIG["volume"]["short_ema"]
            v_long = CONFIG["volume"]["long_ema"]
            df['Vol_Short'] = df['Volume'].ewm(span=v_short, adjust=False).mean()
            df['Vol_Long'] = df['Volume'].ewm(span=v_long, adjust=False).mean()

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
