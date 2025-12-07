import numpy as np
import math
import pandas as pd

class PositionSizer:
    def __init__(self, config):
        self.config = config

    def calculate_position_size(self, symbol, df_orig):
        """
        Calculates entry, stop loss, and position size for a single stock
        based on Volatility (ATR) and Account Risk %.
        """
        # Work on a copy to avoid affecting the global cache
        df = df_orig.copy()
        
        # 1. Calculate True Range (TR)
        # TR is the largest of: (High-Low), |High-PrevClose|, |Low-PrevClose|
        df['H-L'] = df['High'] - df['Low']
        df['H-PC'] = abs(df['High'] - df['Close'].shift(1))
        df['L-PC'] = abs(df['Low'] - df['Close'].shift(1))
        
        df['TR'] = df[['H-L', 'H-PC', 'L-PC']].max(axis=1)
        
        # 2. Calculate ATR (Average True Range)
        # We use a rolling mean of the TR
        atr_period = self.config['risk']['atr_period']
        df['ATR'] = df['TR'].rolling(window=atr_period).mean()
        
        # --- Get Latest Data ---
        curr = df.iloc[-1]
        
        # 3. Define Trade Variables
        entry_price = curr['Close']
        atr_value = curr['ATR']
        
        # Safety Check: If ATR is NaN (not enough data), return None
        if pd.isna(atr_value):
            return None

        # 4. Calculate Stop Loss Price
        # Stop = Entry - (ATR * Multiplier)
        stop_distance = atr_value * self.config['risk']['atr_multiplier']
        stop_loss_price = entry_price - stop_distance
        
        # 5. Position Sizing Math
        # Total money to risk = Account Size * Risk%
        account_risk_amt = self.config['risk']['account_size'] * self.config['risk']['risk_per_trade']
        
        # Risk per share = Entry - Stop
        risk_per_share = entry_price - stop_loss_price
        
        # Number of shares = Total Risk / Risk Per Share
        # We use math.floor to round down to the nearest whole share
        if risk_per_share > 0:
            shares = math.floor(account_risk_amt / risk_per_share)
        else:
            shares = 0 # Should not happen in a long trade unless data is corrupted
            
        return {
            "Symbol": symbol,
            "Entry_Price": round(entry_price, 2),
            "ATR": round(atr_value, 2),
            "Stop_Loss": round(stop_loss_price, 2),
            "Stop_Dist_%": round((stop_distance / entry_price) * 100, 2),
            "Risk_Amt": round(account_risk_amt, 2),
            "Shares": shares,
            "Position_Value": round(shares * entry_price, 2)
        }
