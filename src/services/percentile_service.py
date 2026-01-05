import pandas as pd
from datetime import datetime, date
from config import *
from config import Strategy1Parameters as StrategyParams
from repositories import IndicatorsRepository, MarketDataRepository, PercentileRepository
from utils import (score_rsi_regime, score_percent_b, score_trend_extension,
                   z_score_normalize, percentile_rank)

percentile_repo = PercentileRepository()
indicators_repo = IndicatorsRepository()
marketdata_repo = MarketDataRepository()
logger = setup_logger(name="Orchestrator")


class PercentileService:
    """
    Multi-Factor Momentum Scorecard for Indian Markets
    Based on quantitative equity ranking framework
    (Renamed from RankingService)
    """
    def __init__(self):
        self.strategy_params = StrategyParams()

    @staticmethod
    def _calculate_percentile_ranks(metrics_df) -> pd.DataFrame:
        """Calculate percentile ranks across the universe"""

        # Define metrics to rank
        rank_cols = {
            'ema_50_slope': 'trend_rank',
            'ppo_12_26_9': 'momentum_ppo_rank',
            'ppoh_12_26_9': 'momentum_ppoh_rank',
            'risk_adjusted_return': 'efficiency_rank',
            'rvol': 'rvolume_rank',
            'price_vol_correlation': 'price_vol_corr_rank',
            'bbb_20_2_2': 'structure_rank'
        }
        
        for col, rank_name in rank_cols.items():
            if col in metrics_df.columns:
                metrics_df[rank_name] = percentile_rank(metrics_df[col])
        
        metrics_df['momentum_rsi_rank'] = score_rsi_regime(metrics_df['rsi_signal_ema_3'])
        metrics_df['trend_extension_rank'] = score_trend_extension(metrics_df['distance_from_ema_200'])
        metrics_df['trend_start_rank'] = score_trend_extension(metrics_df['distance_from_ema_50'])
        metrics_df['structure_bb_rank'] = score_percent_b(metrics_df['percent_b'])

        return metrics_df

    def _calculate_weighted_composite(self, metrics_df) -> pd.DataFrame:
        """Calculate weighted composite score"""
        
        # Aggregate trend (combine EMA slope and extension)
        if 'trend_rank' in metrics_df.columns and 'trend_extension_rank' in metrics_df.columns:
            metrics_df['final_trend_score'] = (
                metrics_df['trend_rank'].fillna(0) * self.strategy_params.trend_rank_weight +
                metrics_df['trend_extension_rank'].fillna(0) * self.strategy_params.trend_extension_rank_weight
            )
        else:
            metrics_df['final_trend_score'] = metrics_df.get('trend_rank', 0)

        # Aggregate momentum (RSI + PPO)
        momentum_cols = [c for c in ['momentum_rsi_rank', 'momentum_ppo_rank', 'momentum_ppoh_rank'] 
                        if c in metrics_df.columns]
        if momentum_cols:
            metrics_df['final_momentum_score'] = (metrics_df["momentum_rsi_rank"] * self.strategy_params.momentum_rsi_rank_weight + 
                                              metrics_df["momentum_ppo_rank"] * self.strategy_params.momentum_ppo_rank_weight + 
                                              metrics_df["momentum_ppoh_rank"] * self.strategy_params.momentum_ppoh_rank_weight)
        else:
            metrics_df['final_momentum_score'] = 0
        
        metrics_df['final_vol_score'] = (metrics_df["rvolume_rank"] * self.strategy_params.rvolume_rank_weight + 
                               metrics_df["price_vol_corr_rank"] * self.strategy_params.price_vol_corr_rank_weight)

        # Combine BB Width and %B for structure (as per report Section 4.1)
        metrics_df['final_structure_score'] = (
            metrics_df.get('structure_rank', 0) * self.strategy_params.structure_rank_weight +
            metrics_df.get('structure_bb_rank', 0) * self.strategy_params.structure_bb_rank_weight
        )

        # Calculate composite score
        metrics_df['composite_score'] = (
            self.strategy_params.trend_strength_weight * metrics_df.get('final_trend_score', 0) +
            self.strategy_params.momentum_velocity_weight * metrics_df.get('final_momentum_score', 0) +
            self.strategy_params.risk_efficiency_weight * metrics_df.get('efficiency_rank', 0) +
            self.strategy_params.conviction_weight * metrics_df.get('final_vol_score', 0) +
            self.strategy_params.structure_weight * metrics_df.get('final_structure_score', 0)
        )
        return metrics_df

    def _apply_universe_penalties(self, metrics_df) -> pd.DataFrame:
        """Apply penalty box rules across universe"""
        metrics_df.loc[metrics_df['ema_200'] > metrics_df['close'], 'composite_score'] = 0
        metrics_df.loc[metrics_df['atrr_14'] / metrics_df['atrr_14'].shift(2) > self.strategy_params.atr_threshold, 'composite_score'] = 0
        metrics_df.loc[metrics_df['ema_50'] > metrics_df['close'], 'composite_score'] = 0
        metrics_df['composite_score'] = metrics_df['composite_score'].fillna(0)
        return metrics_df

    # ============= COMPOSITE SCORECARD =============
    def calculate_composite_score(self, metrics_df) -> pd.DataFrame:
        """
        Calculate composite score for multiple stocks
        Args:
            metrics_df: DataFrame with OHLCV data
        Returns:
            DataFrame with stocks and their factor scores + composite score
        """
        metrics_df = self._calculate_percentile_ranks(metrics_df)

        req_cols = [
            'tradingsymbol',
            'ema_50_slope',
            'trend_rank',
            'distance_from_ema_200',
            'trend_extension_rank',
            'distance_from_ema_50',
            'trend_start_rank',
            'rsi_signal_ema_3',
            'momentum_rsi_rank',
            'ppo_12_26_9',
            'momentum_ppo_rank',
            'ppoh_12_26_9',
            'momentum_ppoh_rank',
            'risk_adjusted_return',
            'efficiency_rank',
            'rvol',
            'rvolume_rank',
            'price_vol_correlation',
            'price_vol_corr_rank',
            'bbb_20_2_2',
            'structure_rank',
            'percent_b',
            'structure_bb_rank',
        ]
        return metrics_df[req_cols]

    @staticmethod
    def query_to_dict(results):
        return [
            {c.name: getattr(row, c.name) for c in row.__table__.columns}
            for row in results
        ]

    def generate_percentile(self, date=None):
        """
        Orchestrates the percentile calculation process:
        1. Fetch instruments
        2. Fetch latest price and indicator data for each instrument
        3. Construct DataFrames
        4. Calculate percentile ranks
        5. Save to percentile table with date
        """
        logger.info("Starting Percentile Calculation...")
        if not date:
            max_date = marketdata_repo.get_max_date_from_table()
            date_range = {
                "start_date": max_date,
                "end_date": max_date
            }
        else:
            date_range = {
                "start_date": date,
                "end_date": date
            }

        price_data_list = self.query_to_dict(marketdata_repo.get_prices_for_all_stocks(date_range))
        indicators_data_list = self.query_to_dict(indicators_repo.get_indicators_for_all_stocks(date_range))

        # 3. Create DataFrames
        stocks_df = pd.DataFrame(price_data_list)
        metrics_df = pd.DataFrame(indicators_data_list)

        if len(stocks_df) == 0 or len(metrics_df) == 0:
            logger.info("No data found for date: {}".format(date))
            return None

        metrics_df = pd.merge(metrics_df, stocks_df, on='tradingsymbol', how='inner')
        ranked_df = self.calculate_composite_score(metrics_df)
        
        # Add percentile date
        percentile_date = date
        ranked_df['percentile_date'] = percentile_date
        
        # 5. Save to database
        logger.info("Saving percentiles to database...")
        response = percentile_repo.delete(percentile_date)
        if response:
            percentile_repo.bulk_insert(ranked_df.to_dict('records'))
        else:
            logger.error("Failed to delete existing percentiles for today, cannot save new percentiles")
            return None
        logger.info(f"Saved {len(ranked_df)} percentiles to database for {percentile_date}")
        return True

    def backfill_percentiles(self):
        """
        Generates percentiles for all dates since the last updated date in the percentile table.
        If no percentiles exist, starts from the earliest available market data date.
        """
        last_percentile_date = percentile_repo.get_max_percentile_date()

        if last_percentile_date:
            start_date = last_percentile_date
        else:
            start_date = marketdata_repo.get_min_date_from_table()

        current_date = pd.Timestamp.now().normalize()
        if isinstance(start_date, (datetime, date)):
            start_date = pd.Timestamp(start_date)

        while start_date <= current_date:
            self.generate_percentile(start_date)
            start_date += pd.Timedelta(days=1)
