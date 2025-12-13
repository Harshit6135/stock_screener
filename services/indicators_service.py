import pandas as pd
import pandas_ta as ta

class IndicatorsService:

    def ema(self, df, length, column_name="close"):
        return df.ta.ema(close=column_name, length=length)

    def rsi(self, df, inp, column_name='Close'):
        length, smooth_length = inp
        rsi = df.ta.rsi(close=column_name, length=length)
        rsi_df = pd.DataFrame(rsi)
        rsi_signal = self.ema(rsi_df, smooth_length, rsi_df.columns[-1])

        return {
            "": rsi, "signal": rsi_signal
        }

    def roc(self, df, length, column_name="close"):
        return df.ta.roc(close=column_name, length=length)

    def stoch(self, df, inp, column_names=("High", "Low", "Close")):
        k_period, d_period = inp
        stoch = df.ta.stoch(high=column_names[0], low=column_names[1], close=column_names[2], k=k_period, d=d_period)
        return {
            "k": stoch[stoch.columns[0]],
            "d": stoch[stoch.columns[1]]
        }

    def macd(self, df, inp, column_name="close"):
        fast, slow, signal = inp
        macd = df.ta.macd(close=column_name, fast=fast, slow=slow, signal=signal)
        return {
            "": macd[macd.columns[0]],
            "signal": macd[macd.columns[2]]
        }

    def bollinger_bands(self, df, inp, column_name="close"):
        window, std, hist_low = inp
        bbands = df.ta.bbands(close=column_name, length=window, std=std)
        if hist_low:
            hist_low_bbw = self.min_lookback(bbands[bbands.columns[3]], hist_low)
        else:
            hist_low_bbw = pd.DataFrame()
        return {
            "lower": bbands[bbands.columns[0]],
            "upper": bbands[bbands.columns[2]],
            "sma": bbands[bbands.columns[1]],
            "bbw": bbands[bbands.columns[3]],
            "hist_low": hist_low_bbw
        }

    def min_lookback(self, df, lookback_days):
        return df.rolling(window=lookback_days).min()

    def max_lookback(self, df, lookback_days):
        return df.rolling(window=lookback_days).max()

    def update_indicators_to_db(self, df, indicators_config):

        indicators_map = {
            'ema': self.ema,
            'rsi': self.rsi,
            'roc': self.roc,
            'stoch': self.stoch,
            'macd': self.macd,
            'bbands': self.bollinger_bands
        }
        indicators_output = {
        }

        for indicator_name, config in indicators_config.items():
            for inp in config:
                col_name = f"{indicator_name}_{"_".join(map(str, inp)) if isinstance(inp, tuple) else inp}"
                if indicator_name in indicators_map:
                    values = indicators_map[indicator_name](df, inp)
                    if isinstance(values, dict):
                        for key, value in values.items():
                            if key:
                                indic_name = f"{col_name}_{key}"
                                indicators_output[indic_name] = value
                            else:
                                indicators_output[col_name] = value
                    else:
                        indicators_output[col_name] = values
                elif indicator_name == "volume":
                    values = self.ema(df, inp, "volume")
                    indicators_output[col_name] = values
        return indicators_output

    def consolidate_indicators(self):
        return ""


    def calculate_rvol(self, df: pd.DataFrame) -> pd.Series:
            """
            Relative Volume: Current volume / 20-day average volume
            Measures participation surprise
            """
            return df['volume'] / df['volume'].rolling(20).mean()
        
    def calculate_volume_price_correlation(self, df: pd.DataFrame, 
                                        lookback: int = 10) -> pd.Series:
        """
        Pearson correlation between price changes and volume
        Positive = accumulation, Negative = distribution
        """
        price_change = df['close'].pct_change()
        return price_change.rolling(lookback).corr(df['volume'])
    
    def calculate_ema_slope(self, df: pd.DataFrame, 
                        period: int = 50, 
                        lookback: int = 5) -> pd.Series:
        """
        Annualized slope of EMA
        Measures trend velocity
        """
        ema = df['close'].ewm(span=period, adjust=False).mean()
        slope = (ema - ema.shift(lookback)) / ema.shift(lookback)
        return slope
    
    def calculate_distance_from_ema(self, df: pd.DataFrame, 
                                period: int = 200) -> pd.Series:
        """
        Percentage distance from EMA
        (Price - EMA) / EMA
        """
        ema = df['close'].ewm(span=period, adjust=False).mean()
        return (df['close'] - ema) / ema
    
    def calculate_bollinger_width(self, df: pd.DataFrame, 
                                period: int = 20, 
                                std_dev: int = 2) -> pd.Series:
        """
        Bollinger Band Width: (Upper - Lower) / Middle
        Measures volatility compression/expansion
        """
        sma = df['close'].rolling(period).mean()
        std = df['close'].rolling(period).std()
        upper = sma + (std_dev * std)
        lower = sma - (std_dev * std)
        return (upper - lower) / sma
    
    def calculate_percent_b(self, df: pd.DataFrame, 
                        period: int = 20, 
                        std_dev: int = 2) -> pd.Series:
        """
        %B: Position within Bollinger Bands
        (Price - Lower) / (Upper - Lower)
        """
        sma = df['close'].rolling(period).mean()
        std = df['close'].rolling(period).std()
        upper = sma + (std_dev * std)
        lower = sma - (std_dev * std)
        return (df['close'] - lower) / (upper - lower)
    
    def calculate_ppo(self, df: pd.DataFrame, 
                    fast: int = 12, 
                    slow: int = 26) -> pd.Series:
        """
        Percentage Price Oscillator (normalized MACD)
        (EMA_fast - EMA_slow) / EMA_slow * 100
        """
        ema_fast = df['close'].ewm(span=fast, adjust=False).mean()
        ema_slow = df['close'].ewm(span=slow, adjust=False).mean()
        return (ema_fast - ema_slow) / ema_slow * 100
    
    def calculate_risk_adjusted_return(self, df: pd.DataFrame, 
                                    return_period: int = 20,
                                    atr_period: int = 14) -> pd.Series:
        """
        Risk-Adjusted Momentum (Sharpe-like)
        ROC / (ATR / Price)
        """
        roc = df['close'].pct_change(return_period)
        
        # Calculate ATR
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = ranges.max(axis=1)
        atr = true_range.rolling(atr_period).mean()
        
        normalized_atr = atr / df['close']
        return roc / normalized_atr


    def _calculate_all_metrics(self, df: pd.DataFrame) -> Dict[str, pd.Series]:
        """Calculate all technical metrics for a single stock"""
        
        # Ensure we have required columns
        required = ['close', 'high', 'low', 'volume']
        if not all(col in df.columns for col in required):
            raise ValueError(f"Missing required columns: {required}")
        
        metrics = {}
        
        # Trend Strength Metrics
        metrics['ema_50_slope'] = self.calculate_ema_slope(df, 50, 5)
        metrics['dist_200'] = self.calculate_distance_from_ema(df, 200)
        metrics['trend_extension_score'] = self.score_trend_extension(
            metrics['dist_200'])
        
        # Momentum Velocity Metrics
        if 'rsi' in df.columns:
            metrics['rsi_smoothed'] = df['rsi'].rolling(3).mean()
            metrics['rsi_regime_score'] = self.score_rsi_regime(
                metrics['rsi_smoothed'])
        
        metrics['ppo'] = self.calculate_ppo(df, 12, 26)
        
        # Risk Efficiency Metrics
        metrics['risk_adj_return'] = self.calculate_risk_adjusted_return(
            df, 20, 14)
        
        # Conviction Metrics
        metrics['rvol'] = self.calculate_rvol(df)
        metrics['vol_price_corr'] = self.calculate_volume_price_correlation(
            df, 10)
        
        # Structure Metrics
        metrics['bb_width'] = self.calculate_bollinger_width(df, 20, 2)
        metrics['percent_b'] = self.calculate_percent_b(df, 20, 2)
        metrics['percent_b_score'] = self.score_percent_b(metrics['percent_b'])
        
        return metrics
    
    def calculate_rvol(self, df: pd.DataFrame, period: int = 20) -> pd.Series:
        """
        Relative Volume: Current volume / SMA of volume
        Measures participation surprise
        """
        vol_sma = ta.sma(df['volume'], length=period)
        return df['volume'] / vol_sma
    
    def calculate_volume_price_correlation(self, df: pd.DataFrame, 
                                          lookback: int = 10) -> pd.Series:
        """
        Pearson correlation between price changes and volume
        Positive = accumulation, Negative = distribution
        """
        price_change = df['close'].pct_change()
        corr = price_change.rolling(lookback).corr(df['volume'])
        return corr
    
    def calculate_ema_slope(self, df: pd.DataFrame, 
                           period: int = 50, 
                           lookback: int = 5) -> pd.Series:
        """
        Annualized slope of EMA - Measures trend velocity
        """
        ema = ta.ema(df['close'], length=period)
        slope = (ema - ema.shift(lookback)) / ema.shift(lookback)
        return slope
    
    def calculate_distance_from_ema(self, df: pd.DataFrame, 
                                   period: int = 200) -> pd.Series:
        """
        Percentage distance from EMA: (Price - EMA) / EMA
        """
        ema = ta.ema(df['close'], length=period)
        return (df['close'] - ema) / ema
    
    def calculate_ppo(self, df: pd.DataFrame, 
                     fast: int = 12, 
                     slow: int = 26,
                     signal: int = 9) -> pd.Series:
        """
        Percentage Price Oscillator (normalized MACD)
        Uses pandas_ta built-in PPO
        """
        ppo = ta.ppo(df['close'], fast=fast, slow=slow, signal=signal)
        return ppo[f'PPO_{fast}_{slow}_{signal}'] if isinstance(ppo, pd.DataFrame) else ppo
    
    def calculate_risk_adjusted_return(self, df: pd.DataFrame, 
                                      return_period: int = 20,
                                      atr_period: int = 14) -> pd.Series:
        """
        Risk-Adjusted Momentum (Sharpe-like): ROC / (ATR / Price)
        """
        roc = ta.roc(df['close'], length=return_period)
        atr = ta.atr(df['high'], df['low'], df['close'], length=atr_period)
        
        normalized_atr = atr / df['close']
        return roc / normalized_atr

def _calculate_all_metrics(self, df: pd.DataFrame) -> Dict[str, pd.Series]:
        """Calculate all technical metrics for a single stock using pandas_ta"""
        
        # Ensure we have required columns
        required = ['close', 'high', 'low', 'volume']
        if not all(col in df.columns for col in required):
            raise ValueError(f"Missing required columns: {required}")
        
        metrics = {}
        
        # ===== TREND STRENGTH METRICS =====
        metrics['ema_50_slope'] = self.calculate_ema_slope(df, 50, 5)
        metrics['dist_200'] = self.calculate_distance_from_ema(df, 200)
        metrics['trend_extension_score'] = self.score_trend_extension(
            metrics['dist_200'])
        
        # ===== MOMENTUM VELOCITY METRICS =====
        # RSI
        rsi = ta.rsi(df['close'], length=14)
        metrics['rsi_smoothed'] = rsi.rolling(3).mean()
        metrics['rsi_regime_score'] = self.score_rsi_regime(
            metrics['rsi_smoothed'])
        
        # PPO (Percentage Price Oscillator - normalized MACD)
        metrics['ppo'] = self.calculate_ppo(df, 12, 26, 9)
        
        # ===== RISK EFFICIENCY METRICS =====
        metrics['risk_adj_return'] = self.calculate_risk_adjusted_return(
            df, 20, 14)
        
        # ===== CONVICTION METRICS =====
        metrics['rvol'] = self.calculate_rvol(df, 20)
        metrics['vol_price_corr'] = self.calculate_volume_price_correlation(
            df, 10)
        
        # ===== STRUCTURE METRICS =====
        # Bollinger Bands
        bbands = ta.bbands(df['close'], length=20, std=2)
        if isinstance(bbands, pd.DataFrame):
            # Calculate BB Width
            metrics['bb_width'] = (
                (bbands[f'BBU_20_2.0'] - bbands[f'BBL_20_2.0']) / 
                bbands[f'BBM_20_2.0']
            )
            # Calculate %B
            metrics['percent_b'] = (
                (df['close'] - bbands[f'BBL_20_2.0']) / 
                (bbands[f'BBU_20_2.0'] - bbands[f'BBL_20_2.0'])
            )
            metrics['percent_b_score'] = self.score_percent_b(
                metrics['percent_b'])
        
        return metrics


    def calculate(df):
    """Fetch data and calculate all technical indicators for ranking"""
    try:
        # Fetch Data
        
        # Basic Price Data
        df['Close'] = df['Close']
        df['High'] = df['High']
        df['Low'] = df['Low']
        df['Volume'] = df['Volume']
        
        # --- 1. VOLUME METRICS ---
        df['Vol_SMA_20'] = df['Volume'].rolling(20).mean()
        df['RVOL'] = df['Volume'] / df['Vol_SMA_20']
        
        # Volume-Price Correlation (10-day)
        df['Price_Change'] = df['Close'].pct_change()
        df['Vol_Price_Corr'] = df['Price_Change'].rolling(10).corr(df['Volume'])
        
        # --- 2. TREND METRICS (EMA) ---
        df['EMA_50'] = ta.ema(df['Close'], length=50)
        df['EMA_200'] = ta.ema(df['Close'], length=200)
        
        # Trend Velocity: Slope of 50 EMA (5-day rate of change)
        df['EMA_50_Slope'] = df['EMA_50'].pct_change(5)
        
        # Trend Extension: Distance from 200 EMA (%)
        df['Dist_200'] = (df['Close'] - df['EMA_200']) / df['EMA_200']
        
        # Golden Cross Status (50 EMA above 200 EMA)
        df['Golden_Cross'] = (df['EMA_50'] > df['EMA_200']).astype(int)
        
        # --- 3. MOMENTUM METRICS ---
        # RSI with 3-day smoothing
        df['RSI_Raw'] = ta.rsi(df['Close'], length=14)
        df['RSI_Smooth'] = df['RSI_Raw'].rolling(3).mean()
        
        # PPO (Percentage Price Oscillator) - normalized MACD
        ppo = ta.ppo(df['Close'], fast=12, slow=26, signal=9)
        df['PPO'] = ppo['PPO_12_26_9'] if ppo is not None else 0
        df['PPO_Hist'] = ppo['PPOh_12_26_9'] if ppo is not None else 0
        df['PPO_Hist_Slope'] = df['PPO_Hist'].diff()
        
        # --- 4. VOLATILITY METRICS (Bollinger Bands) ---
        bb = ta.bbands(df['Close'], length=20, std=2)
        if bb is not None:
            df['BB_Upper'] = bb['BBU_20_2.0']
            df['BB_Lower'] = bb['BBL_20_2.0']
            df['BB_Mid'] = bb['BBM_20_2.0']
            
            # Bollinger Band Width (%)
            df['BB_Width'] = (df['BB_Upper'] - df['BB_Lower']) / df['BB_Mid']
            
            # %B Indicator (position within bands)
            df['BB_PercentB'] = (df['Close'] - df['BB_Lower']) / (df['BB_Upper'] - df['BB_Lower'])
            
            # BB Width Rate of Change
            df['BB_Width_ROC'] = df['BB_Width'].pct_change(5)
        
        # --- 5. RISK METRICS (ATR) ---
        df['ATR_14'] = ta.atr(df['High'], df['Low'], df['Close'], length=14)
        df['ATR_Pct'] = df['ATR_14'] / df['Close']
        
        # 20-day Rate of Change
        df['ROC_20'] = df['Close'].pct_change(20)
        
        # Risk-Adjusted Momentum (Efficiency Ratio)
        df['Efficiency'] = df['ROC_20'] / df['ATR_Pct']
        
        # 6-month momentum for longer-term efficiency
        df['ROC_126'] = df['Close'].pct_change(126)
        df['Efficiency_6M'] = df['ROC_126'] / df['ATR_Pct']
        
        # --- PENALTY BOX CHECKS ---
        latest = df.iloc[-1]
        
        # Check for earnings volatility spike
        atr_spike = df['ATR_14'].pct_change().iloc[-2:].max() > 1.0
        
        # Liquidity check (approximate - needs actual rupee turnover)
        avg_turnover = (df['Close'] * df['Volume']).tail(20).mean() / 10000000  # in Crores
        
        result = {
            'Close': latest['Close'],
            'RVOL': latest['RVOL'],
            'Vol_Price_Corr': latest['Vol_Price_Corr'],
            'EMA_50': latest['EMA_50'],
            'EMA_200': latest['EMA_200'],
            'EMA_50_Slope': latest['EMA_50_Slope'],
            'Dist_200': latest['Dist_200'],
            'Golden_Cross': latest['Golden_Cross'],
            'RSI_Smooth': latest['RSI_Smooth'],
            'PPO': latest['PPO'],
            'PPO_Hist_Slope': latest['PPO_Hist_Slope'],
            'BB_Width': latest['BB_Width'],
            'BB_PercentB': latest['BB_PercentB'],
            'BB_Width_ROC': latest['BB_Width_ROC'],
            'ATR_14': latest['ATR_14'],
            'ATR_Pct': latest['ATR_Pct'],
            'Efficiency': latest['Efficiency'],
            'Efficiency_6M': latest['Efficiency_6M'],
            'ATR_Spike': atr_spike,
            'Avg_Turnover_Cr': avg_turnover,
            'Broken_Trend': latest['Close'] < latest['EMA_200']
        }
        
        return result

# ==========================================
# 1. DATA FETCHING & INDICATOR CALCULATION
# ==========================================
def fetch_and_calculate(df):
    """Fetch data and calculate all technical indicators for ranking"""
    try:

        
        # Basic Price Data
        df['Close'] = df['Close']
        df['High'] = df['High']
        df['Low'] = df['Low']
        df['Volume'] = df['Volume']
        
        # --- 1. VOLUME METRICS ---
        df['Vol_SMA_20'] = df['Volume'].rolling(20).mean()
        df['RVOL'] = df['Volume'] / df['Vol_SMA_20']
        
        # Volume-Price Correlation (10-day)
        df['Price_Change'] = df['Close'].pct_change()
        df['Vol_Price_Corr'] = df['Price_Change'].rolling(10).corr(df['Volume'])
        
        # --- 2. TREND METRICS (EMA) ---
        df['EMA_50'] = ta.ema(df['Close'], length=50)
        df['EMA_200'] = ta.ema(df['Close'], length=200)
        
        # Trend Velocity: Slope of 50 EMA (5-day rate of change)
        df['EMA_50_Slope'] = df['EMA_50'].pct_change(5)
        
        # Trend Extension: Distance from 200 EMA (%)
        df['Dist_200'] = (df['Close'] - df['EMA_200']) / df['EMA_200']
        
        # Golden Cross Status (50 EMA above 200 EMA)
        df['Golden_Cross'] = (df['EMA_50'] > df['EMA_200']).astype(int)
        
        # --- 3. MOMENTUM METRICS ---
        # RSI with 3-day smoothing
        df['RSI_Raw'] = ta.rsi(df['Close'], length=14)
        df['RSI_Smooth'] = df['RSI_Raw'].rolling(3).mean()
        
        # PPO (Percentage Price Oscillator) - normalized MACD
        ppo = ta.ppo(df['Close'], fast=12, slow=26, signal=9)
        df['PPO'] = ppo['PPO_12_26_9'] if ppo is not None else 0
        df['PPO_Hist'] = ppo['PPOh_12_26_9'] if ppo is not None else 0
        df['PPO_Hist_Slope'] = df['PPO_Hist'].diff()
        
        # --- 4. VOLATILITY METRICS (Bollinger Bands) ---
        bb = ta.bbands(df['Close'], length=20, std=2)
        if bb is not None:
            df['BB_Upper'] = bb['BBU_20_2.0']
            df['BB_Lower'] = bb['BBL_20_2.0']
            df['BB_Mid'] = bb['BBM_20_2.0']
            
            # Bollinger Band Width (%)
            df['BB_Width'] = (df['BB_Upper'] - df['BB_Lower']) / df['BB_Mid']
            
            # %B Indicator (position within bands)
            df['BB_PercentB'] = (df['Close'] - df['BB_Lower']) / (df['BB_Upper'] - df['BB_Lower'])
            
            # BB Width Rate of Change
            df['BB_Width_ROC'] = df['BB_Width'].pct_change(5)
        
        # --- 5. RISK METRICS (ATR) ---
        df['ATR_14'] = ta.atr(df['High'], df['Low'], df['Close'], length=14)
        df['ATR_Pct'] = df['ATR_14'] / df['Close']
        
        # 20-day Rate of Change
        df['ROC_20'] = df['Close'].pct_change(20)
        
        # Risk-Adjusted Momentum (Efficiency Ratio)
        df['Efficiency'] = df['ROC_20'] / df['ATR_Pct']
        
        # 6-month momentum for longer-term efficiency
        df['ROC_126'] = df['Close'].pct_change(126)
        df['Efficiency_6M'] = df['ROC_126'] / df['ATR_Pct']
        
        # --- PENALTY BOX CHECKS ---
        latest = df.iloc[-1]
        
        # Check for earnings volatility spike
        atr_spike = df['ATR_14'].pct_change().iloc[-2:].max() > 1.0
        
        # Liquidity check (approximate - needs actual rupee turnover)
        avg_turnover = (df['Close'] * df['Volume']).tail(20).mean() / 10000000  # in Crores
        
        result = {
            'Close': latest['Close'],
            'RVOL': latest['RVOL'],
            'Vol_Price_Corr': latest['Vol_Price_Corr'],
            'EMA_50': latest['EMA_50'],
            'EMA_200': latest['EMA_200'],
            'EMA_50_Slope': latest['EMA_50_Slope'],
            'Dist_200': latest['Dist_200'],
            'Golden_Cross': latest['Golden_Cross'],
            'RSI_Smooth': latest['RSI_Smooth'],
            'PPO': latest['PPO'],
            'PPO_Hist_Slope': latest['PPO_Hist_Slope'],
            'BB_Width': latest['BB_Width'],
            'BB_PercentB': latest['BB_PercentB'],
            'BB_Width_ROC': latest['BB_Width_ROC'],
            'ATR_14': latest['ATR_14'],
            'ATR_Pct': latest['ATR_Pct'],
            'Efficiency': latest['Efficiency'],
            'Efficiency_6M': latest['Efficiency_6M'],
            'ATR_Spike': atr_spike,
            'Avg_Turnover_Cr': avg_turnover,
            'Broken_Trend': latest['Close'] < latest['EMA_200']
        }
        
        return result
        
    except Exception as e:
        print(f"Error {ticker}: {e}")
        return None