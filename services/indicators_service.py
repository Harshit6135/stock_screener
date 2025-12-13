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