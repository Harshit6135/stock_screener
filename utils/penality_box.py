def apply_penalty_box(self, df: pd.DataFrame, 
                         scores: pd.Series) -> pd.Series:
        """
        Apply hard filters that set score to 0 for toxic conditions
        """
        penalized_scores = scores.copy()
        
        # Broken Trend: Price < 200 EMA
        ema_200 = df['close'].ewm(span=200, adjust=False).mean()
        penalized_scores[df['close'] < ema_200] = 0
        
        # ATR Spike (Earnings volatility)
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = ranges.max(axis=1)
        atr = true_range.rolling(14).mean()
        atr_spike = atr / atr.shift(2) > 2.0  # 100% spike in 2 days
        penalized_scores[atr_spike] = 0
        
        # Liquidity trap (if turnover data available)
        if 'turnover' in df.columns:
            penalized_scores[df['turnover'] < 50000000] = 0  # < 5 Cr
        
        return penalized_scores

def apply_penalty_box(self, df: pd.DataFrame, 
                         scores: pd.Series) -> pd.Series:
        """
        Apply hard filters that set score to 0 for toxic conditions
        """
        penalized_scores = scores.copy()
        
        # Broken Trend: Price < 200 EMA
        ema_200 = ta.ema(df['close'], length=200)
        penalized_scores[df['close'] < ema_200] = 0
        
        # ATR Spike (Earnings volatility) - 100% spike in 2 days
        atr = ta.atr(df['high'], df['low'], df['close'], length=14)
        atr_spike = atr / atr.shift(2) > 2.0
        penalized_scores[atr_spike] = 0
        
        # Liquidity trap (if turnover data available)
        if 'turnover' in df.columns:
            penalized_scores[df['turnover'] < 50000000] = 0  # < 5 Cr
        
        return penalized_scores