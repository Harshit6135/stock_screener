import pandas as pd
import pandas_ta as ta

from strategy.strategy_1 import momentum_strategy, derived_strategy, additional_parameters

class IndicatorsService:

    @staticmethod
    def calculate_volume_price_correlation(df_close, df_volume, lookback: int = 10) -> pd.Series:
        """
        Pearson correlation between price changes and volume
        Positive = accumulation, Negative = distribution
        """
        price_change = df_close.pct_change()
        return price_change.rolling(lookback).corr(df_volume)

    @staticmethod
    def calculate_percent_b(df_close, 
                        df_upper, df_lower) -> pd.Series:
        """
        %B: Position within Bollinger Bands
        (Price - Lower) / (Upper - Lower)
        """
        return (df_close - df_lower) / (df_upper - df_lower)

    @staticmethod
    def calculate_ema_slope(ema: pd.Series, 
                            lookback: int = 5) -> pd.Series:
        """
        Annualized slope of EMA - Measures trend velocity
        """
        slope = (ema - ema.shift(lookback)) / ema.shift(lookback)
        return slope

    @staticmethod
    def calculate_distance_from_ema(df_close, ema: pd.Series 
                                    ) -> pd.Series:
            """
            Percentage distance from EMA: (Price - EMA) / EMA
            """
            return (df_close - ema) / ema

    def calculate_indicators(self, df):
        df.ta.study(momentum_strategy)
        df.ta.study(derived_strategy)
        df['price_vol_correlation'] = self.calculate_volume_price_correlation(df['close'], df['volume'], additional_parameters['vol_price_lookback'])
        df['percent_b'] = self.calculate_percent_b(df['close'], df['BBU_20_2.0_2.0'], df['BBL_20_2.0_2.0'])
        df['ema_50_slope'] = self.calculate_ema_slope(df['EMA_50'], additional_parameters['ema_slope_lookback'])
        df['distance_from_ema_200'] = self.calculate_distance_from_ema(df['close'], df['EMA_200'])
        df['risk_adjusted_return'] = df["ROC_20"]/(df['ATRr_14']/df['close'])
        df['rvol'] = df['volume']/df['VOLUME_SMA_20']

        df.columns = df.columns.str.lower().str.replace(".0", "")
        df = df.drop(columns=['open', 'high', 'low', 'close', 'volume'], errors='ignore')
        return df
