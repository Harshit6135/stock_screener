import pandas as pd
pd.set_option('future.no_silent_downcasting', True)

from datetime import datetime, date

from config import setup_logger, StrategyParameters as StrategyParams
from repositories import IndicatorsRepository, MarketDataRepository, PercentileRepository
from utils import percentile_rank
from services import FactorsService


percentile_repo = PercentileRepository()
indicators_repo = IndicatorsRepository()
marketdata_repo = MarketDataRepository()
logger = setup_logger(name="Orchestrator")


class PercentileService:
    """
    Multi-Factor Momentum Scorecard for Indian Markets
    Based on quantitative equity ranking framework
    """
    def __init__(self):
        self.strategy_params = StrategyParams()
        self.factors_service = FactorsService()

    def _calculate_percentiles(self, metrics_df) -> pd.DataFrame:
        """Calculate factor scores via FactorsService, then percentiles"""
        metrics_df = self.factors_service.calculate_all_factors(metrics_df)
        
        factor_cols = {
            'factor_trend': 'trend_percentile',
            'factor_momentum': 'momentum_percentile',
            'factor_efficiency': 'efficiency_percentile',
            'factor_volume': 'volume_percentile',
            'factor_structure': 'structure_percentile'
        }
        for col, percentile_name in factor_cols.items():
            if col in metrics_df.columns:
                metrics_df[percentile_name] = percentile_rank(metrics_df[col])
        
        return metrics_df



    def _validate_count(self, indicators_count: int, date, last_percentile_date) -> None:
        """Compare indicator row count vs last percentile date's count.

        Args:
            indicators_count: Number of indicator rows for the new date.
            date: The date being processed.

        Raises:
            ValueError: If the count difference exceeds 5%.
        """

        last_percentile_rows = percentile_repo.get_percentiles_by_date(
            last_percentile_date
        )
        last_count = len(last_percentile_rows)
        if last_count == 0:
            return

        diff_pct = abs(indicators_count - last_count) / last_count
        logger.info(
            f"Count validation: indicators={indicators_count}, "
            f"last_percentile({last_percentile_date})={last_count}, "
            f"diff={diff_pct:.1%}"
        )
        if diff_pct > 0.05:
            raise ValueError(
                f"Count validation failed for {date}: "
                f"indicators={indicators_count}, "
                f"last_percentile={last_count}, "
                f"diff={diff_pct:.1%} (threshold=5%)"
            )

    def generate_percentile(self, date=None):
        """
        Orchestrates the percentile calculation process:
        1. Fetch instruments
        2. Fetch latest price and indicator data for each instrument
        3. Construct DataFrames
        4. Calculate percentiles
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
        metrics_df = metrics_df.fillna(0).infer_objects(copy=False)

        if len(stocks_df) == 0 or len(metrics_df) == 0:
            logger.info("No data found for date: {}".format(date))
            return None

        stocks_df['avg_turnover'] = stocks_df['close']*stocks_df['volume'] / 10000000
        metrics_df = pd.merge(metrics_df, stocks_df, on='tradingsymbol', how='inner')
        
        # Add percentile date
        percentile_date = date
        metrics_df['percentile_date'] = percentile_date
        metrics_df = self._calculate_percentiles(metrics_df)

        req_cols = [
            'tradingsymbol', 
            'percentile_date', 
            'close',

            #trend Percentile
            'factor_trend',
            'trend_percentile',

            #momentum percentile
            'factor_momentum',
            'momentum_percentile',

            #efficiency percentile
            'factor_efficiency',
            'efficiency_percentile',

            #volume rank
            'factor_volume',
            'volume_percentile',

            #structure rank
            'factor_structure',
            'structure_percentile'
        ]
        percentile_df = metrics_df[req_cols]
        
        # 5. Save to database
        logger.info("Saving percentiles to database...")
        response = percentile_repo.delete(percentile_date)
        if response:
            percentile_repo.bulk_insert(percentile_df.to_dict('records'))
        else:
            logger.error("Failed to delete existing percentiles for today, cannot save new percentiles")
            return None
        logger.info(f"Saved {len(percentile_df)} percentiles to database for {percentile_date}")
        return True

    def backfill_percentiles(self):
        """
        Generates percentiles for all dates since the last updated date in the percentile table.
        If no percentiles exist, starts from the earliest available market data date.

        Runs count validation once at the start before iterating.
        """
        last_percentile_date = percentile_repo.get_max_percentile_date()

        if last_percentile_date:
            start_date = last_percentile_date
        else:
            start_date = marketdata_repo.get_min_date_from_table()

        if isinstance(start_date, (datetime, date)):
            start_date = pd.Timestamp(start_date)

        # One-time count validation at start of run
        max_date = marketdata_repo.get_max_date_from_table()

        if isinstance(max_date, (datetime, date)):
            max_date = pd.Timestamp(max_date)

        while start_date <= max_date:
            self.generate_percentile(start_date)
            start_date += pd.Timedelta(days=1)
    
    @staticmethod
    def query_to_dict(results):
        return [
            {c.name: getattr(row, c.name) for c in row.__table__.columns}
            for row in results
        ]
