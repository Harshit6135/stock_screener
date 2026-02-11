import pandas as pd
from datetime import datetime, date
from config import *
from config import Strategy1Parameters as StrategyParams
from repositories import IndicatorsRepository, MarketDataRepository, PercentileRepository
from utils import percentile_rank
from services.factors_service import FactorsService

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
        self.factors_service = FactorsService()

    def _calculate_percentile_ranks(self, metrics_df) -> pd.DataFrame:
        """Calculate factor scores via FactorsService, then percentile-rank cross-sectionally"""
        
        # Calculate all 5 factors using FactorsService non-linear scoring
        metrics_df = self.factors_service.calculate_all_factors(metrics_df)
        
        # Percentile-rank each factor across the universe
        factor_cols = {
            'factor_trend': 'trend_rank',
            'factor_momentum': 'momentum_rank',
            'factor_efficiency': 'efficiency_rank',
            'factor_volume': 'volume_rank',
            'factor_structure': 'structure_rank'
        }
        
        for col, rank_name in factor_cols.items():
            if col in metrics_df.columns:
                metrics_df[rank_name] = percentile_rank(metrics_df[col])
        
        return metrics_df

    def _calculate_weighted_composite(self, metrics_df) -> pd.DataFrame:
        """Calculate weighted composite score from factor-based percentile ranks"""
        
        # Composite score using spec weights (30/30/20/15/5)
        metrics_df['composite_score'] = (
            self.strategy_params.trend_strength_weight * metrics_df.get('trend_rank', 0) +
            self.strategy_params.momentum_velocity_weight * metrics_df.get('momentum_rank', 0) +
            self.strategy_params.risk_efficiency_weight * metrics_df.get('efficiency_rank', 0) +
            self.strategy_params.conviction_weight * metrics_df.get('volume_rank', 0) +
            self.strategy_params.structure_weight * metrics_df.get('structure_rank', 0)
        )
        return metrics_df

    def _apply_universe_penalties(self, metrics_df) -> pd.DataFrame:
        """Apply penalty box rules and liquidity filter across universe"""
        metrics_df.loc[metrics_df['ema_200'] > metrics_df['close'], 'composite_score'] = 0
        metrics_df.loc[metrics_df['atrr_14'] / metrics_df['atrr_14'].shift(2) > self.strategy_params.atr_threshold, 'composite_score'] = 0
        metrics_df.loc[metrics_df['ema_50'] > metrics_df['close'], 'composite_score'] = 0
        
        # Liquidity filter: exclude stocks with RVOL below 0.5
        if 'rvol' in metrics_df.columns:
            metrics_df.loc[metrics_df['rvol'] < 0.5, 'composite_score'] = 0
        
        metrics_df['composite_score'] = metrics_df['composite_score'].fillna(0)
        return metrics_df

    # ============= COMPOSITE SCORECARD =============
    def calculate_composite_score(self, metrics_df) -> pd.DataFrame:
        """
        Calculate composite score for multiple stocks
        Args:
            metrics_df: DataFrame with OHLCV + indicator data
        Returns:
            DataFrame with stocks and their factor scores + composite score
        """
        metrics_df = self._calculate_percentile_ranks(metrics_df)

        req_cols = [
            'tradingsymbol',
            # Raw factors
            'factor_trend',
            'factor_momentum',
            'factor_efficiency',
            'factor_volume',
            'factor_structure',
            # Percentile ranks
            'trend_rank',
            'momentum_rank',
            'efficiency_rank',
            'volume_rank',
            'structure_rank',
        ]
        
        # Only include columns that exist in the DataFrame
        available_cols = [c for c in req_cols if c in metrics_df.columns]
        return metrics_df[available_cols]

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
