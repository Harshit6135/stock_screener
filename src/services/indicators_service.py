
import pandas as pd
import pandas_ta as ta
pd.set_option('future.no_silent_downcasting', True)

from datetime import timedelta

from repositories import IndicatorsRepository, MarketDataRepository, InstrumentsRepository
from config import setup_logger, ema_strategy, momentum_strategy, derived_strategy, additional_parameters


instr_repo = InstrumentsRepository()
indicators_repo = IndicatorsRepository()
marketdata_repo = MarketDataRepository()
logger = setup_logger(name="Orchestrator")


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
    def calculate_percent_b(df_close, df_upper, df_lower) -> pd.Series:
        """
        %B: Position within Bollinger Bands
        (Price - Lower) / (Upper - Lower)
        """
        return (df_close - df_lower) / (df_upper - df_lower)

    @staticmethod
    def calculate_ema_slope(ema: pd.Series, lookback: int = 5) -> pd.Series:
        """
        Annualized slope of EMA - Measures trend velocity
        """
        slope = (ema - ema.shift(lookback)) / ema.shift(lookback)
        return slope

    @staticmethod
    def calculate_distance_from_ema(df_close, ema: pd.Series) -> pd.Series:
        """
        Percentage distance from EMA: (Price - EMA) / EMA
        """
        return (df_close - ema) / ema

    @staticmethod
    def calculate_atr_spike(atr: pd.Series, lookback: int = 20) -> pd.Series:
        """
        ATR relative to recent average - detects earnings/news volatility
        """
        atr_avg = atr.rolling(window=lookback).mean()
        return atr / atr_avg

    @staticmethod
    def apply_study(df, last_ind_date):
        df.ta.study(ema_strategy)
        date_truncate = last_ind_date - timedelta(days=additional_parameters['truncate_days'])
        df = df[df.index >= date_truncate]
        df.ta.study(momentum_strategy)
        df.ta.study(derived_strategy)
        return df

    def _calculate_derived_indicators(self, df):
        df['price_vol_correlation'] = self.calculate_volume_price_correlation(df['close'], df['volume'], additional_parameters['vol_price_lookback'])
        df['percent_b'] = self.calculate_percent_b(df['close'], df['BBU_20_2.0_2.0'], df['BBL_20_2.0_2.0'])
        df['ema_50_slope'] = self.calculate_ema_slope(df['EMA_50'], additional_parameters['ema_slope_lookback'])
        df['distance_from_ema_200'] = self.calculate_distance_from_ema(df['close'], df['EMA_200'])
        df['distance_from_ema_50'] = self.calculate_distance_from_ema(df['close'], df['EMA_50'])
        df['risk_adjusted_return'] = df["ROC_20"]/(df['ATRr_14']/df['close'])
        df['rvol'] = df['volume']/df['VOL_SMA_20']
        df['atr_spike'] = self.calculate_atr_spike(df['ATRr_14'])

        df['momentum_3m'] = (df['close'].shift(5) / df['close'].shift(65)) - 1
        df['momentum_6m'] = (df['close'].shift(5) / df['close'].shift(130)) - 1
        return df

    def calculate_indicators(self):
        logger.info("Starting to update Indicators (API Mode)...")

        logger.info("Fetching Instruments from DB...")
        instruments = instr_repo.get_all_instruments()

        logger.info("Calculating Indicators for Instruments...")
        yesterday = pd.Timestamp.now().normalize() - pd.Timedelta(days=1)
        
        for i, instr in enumerate(instruments):
            tradingsymbol = instr.tradingsymbol
            instr_token = instr.instrument_token
            exchange = instr.exchange
            log_symb = f"{tradingsymbol} ({instr_token})"
            logger.info(f"Processing {i+1}/{len(instruments)} {log_symb})...")

            last_data_date = marketdata_repo.get_latest_date_by_symbol(tradingsymbol)
            if last_data_date:
                last_data_date = pd.to_datetime(last_data_date.date)
            else:
                logger.error(f"No market data found for {log_symb}")
                continue

            last_ind_date = indicators_repo.get_latest_date_by_symbol(tradingsymbol)
            if last_ind_date:
                last_ind_date = pd.to_datetime(last_ind_date.date)
                if last_ind_date == last_data_date:
                    logger.info(f"Indicators up to date for {log_symb}.")
                    continue
                calc_start_date = last_ind_date - timedelta(days=additional_parameters['ema_200_lookback'])
            else:
                calc_start_date = pd.to_datetime("2000-01-01")
                last_ind_date = calc_start_date

            query_payload = {
                "tradingsymbol": tradingsymbol,
                "start_date": str(calc_start_date.date()),
                "end_date": str(yesterday.date())
            }
            md_output = marketdata_repo.query(query_payload)
            md_list = [{column.name:getattr(row, column.name) for column in row.__table__.columns} for row in md_output]

            if len(md_list)<200:
                logger.error(f"Less than 200 days data")
                continue        

            df_for_ind = pd.DataFrame(md_list)
            df_for_ind['date'] = pd.to_datetime(df_for_ind['date'])
            df_for_ind.set_index('date', inplace=True)
            df_for_ind.sort_index(inplace=True)
            
            logger.info("Calculating indicators...")
            df_for_ind['avg_turnover'] = df_for_ind['close'] * df_for_ind['volume']
            ind_df = self.apply_study(df_for_ind, last_ind_date)
            try:
                ind_df = self._calculate_derived_indicators(ind_df)
            except Exception as e:
                logger.error(f"Error calculating derived indicators for {log_symb}: {str(e)}")
                continue
            ind_df.columns = ind_df.columns.str.lower().str.replace(".0", "")
            ind_df = ind_df.drop(columns=['open', 'high', 'low', 'close', 'volume'], errors='ignore')
            ind_df.reset_index(inplace=True)
            ind_df['tradingsymbol'] = tradingsymbol
            ind_df['exchange'] = exchange

            if last_ind_date:
                next_day = last_ind_date + timedelta(days=1)
                ind_df_filtered = ind_df[ind_df['date'] >= next_day]
            else:
                ind_df_filtered = ind_df
            if ind_df_filtered.empty:
                logger.info(f"No new data to calculate indicators for {log_symb}")
                continue
            
            ind_df_filtered['date'] = ind_df_filtered['date'].dt.date   
            ind_json = ind_df_filtered.to_dict(orient='records')
            indicators_repo.bulk_insert(ind_json)

        logger.info("Indicators updated successfully.")
