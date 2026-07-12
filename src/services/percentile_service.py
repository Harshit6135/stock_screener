import pandas as pd

pd.set_option("future.no_silent_downcasting", True)

from datetime import date, datetime

from config import Strategy2Parameters, StrategyParameters
from config import setup_logger
from repositories import IndicatorsRepository, MarketDataRepository, PercentileRepository
from services.factors_service import FactorsService, FactorsServiceV2
from utils import percentile_rank

percentile_repo = PercentileRepository()
indicators_repo = IndicatorsRepository()
marketdata_repo = MarketDataRepository()
logger = setup_logger(name="Orchestrator")


class PercentileService:
    """
    Multi-Factor Momentum Scorecard for Indian Markets.

    Supports Strategy 1 (default) and Strategy 2 via strategy_id parameter.
    All repo calls are tagged with the strategy_id so rows coexist in the
    same table without collision.
    """

    def __init__(self, strategy_id: str = "strategy1"):
        self.strategy_id = strategy_id
        if strategy_id == "strategy2":
            self.strategy_params = Strategy2Parameters()
            self.factors_service = FactorsServiceV2()
        else:
            self.strategy_params = StrategyParameters()
            self.factors_service = FactorsService()

    def _calculate_percentiles(self, metrics_df) -> pd.DataFrame:
        """Calculate factor scores via FactorsService, then percentiles"""
        metrics_df = self.factors_service.calculate_all_factors(metrics_df)

        factor_cols = {
            "factor_trend": "trend_percentile",
            "factor_momentum": "momentum_percentile",
            "factor_efficiency": "efficiency_percentile",
            "factor_volume": "volume_percentile",
            "factor_structure": "structure_percentile",
        }
        for col, percentile_name in factor_cols.items():
            if col in metrics_df.columns:
                metrics_df[percentile_name] = percentile_rank(metrics_df[col])

        return metrics_df

    def _validate_count(self, indicators_count: int, date, last_percentile_date) -> None:
        """Compare indicator row count vs last percentile date's count."""
        last_percentile_rows = percentile_repo.get_percentiles_by_date(
            last_percentile_date, strategy_id=self.strategy_id
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
        1. Fetch latest price and indicator data
        2. Construct DataFrames
        3. Calculate percentiles using the selected strategy's factor service
        4. Save to percentile table tagged with strategy_id
        """
        logger.info(f"Starting Percentile Calculation [{self.strategy_id}]...")
        if not date:
            max_date = marketdata_repo.get_max_date_from_table()
            date_range = {"start_date": max_date, "end_date": max_date}
        else:
            date_range = {"start_date": date, "end_date": date}

        price_data_list = self.query_to_dict(marketdata_repo.get_prices_for_all_stocks(date_range))
        indicators_data_list = self.query_to_dict(
            indicators_repo.get_indicators_for_all_stocks(date_range)
        )

        stocks_df = pd.DataFrame(price_data_list)
        metrics_df = pd.DataFrame(indicators_data_list)
        metrics_df = metrics_df.fillna(0).infer_objects(copy=False)

        if len(stocks_df) == 0 or len(metrics_df) == 0:
            logger.info("No data found for date: {}".format(date))
            return None

        stocks_df["avg_turnover"] = stocks_df["close"] * stocks_df["volume"] / 10000000
        metrics_df = pd.merge(metrics_df, stocks_df, on="tradingsymbol", how="inner")

        percentile_date = date
        metrics_df["percentile_date"] = percentile_date
        metrics_df["strategy_id"] = self.strategy_id
        metrics_df = self._calculate_percentiles(metrics_df)

        req_cols = [
            "tradingsymbol",
            "percentile_date",
            "strategy_id",
            "close",
            "factor_trend",
            "trend_percentile",
            "factor_momentum",
            "momentum_percentile",
            "factor_efficiency",
            "efficiency_percentile",
            "factor_volume",
            "volume_percentile",
            "factor_structure",
            "structure_percentile",
        ]
        percentile_df = metrics_df[[c for c in req_cols if c in metrics_df.columns]]

        logger.info("Saving percentiles to database...")
        response = percentile_repo.delete(percentile_date, strategy_id=self.strategy_id)
        if response:
            percentile_repo.bulk_insert(percentile_df.to_dict("records"))
        else:
            logger.error(
                "Failed to delete existing percentiles for today, cannot save new percentiles"
            )
            return None
        logger.info(
            f"Saved {len(percentile_df)} percentiles for {percentile_date} [{self.strategy_id}]"
        )
        return True

    def backfill_percentiles(self):
        """
        Generates percentiles for all dates since the last updated date.
        If no percentiles exist, starts from the earliest available market data date.
        """
        last_percentile_date = percentile_repo.get_max_percentile_date(
            strategy_id=self.strategy_id
        )

        if last_percentile_date:
            start_date = last_percentile_date
        else:
            start_date = marketdata_repo.get_min_date_from_table()

        if isinstance(start_date, (datetime, date)):
            start_date = pd.Timestamp(start_date)

        max_date = marketdata_repo.get_max_date_from_table()

        if isinstance(max_date, (datetime, date)):
            max_date = pd.Timestamp(max_date)

        while start_date <= max_date:
            self.generate_percentile(start_date)
            start_date += pd.Timedelta(days=1)

    @staticmethod
    def query_to_dict(results):
        return [{c.name: getattr(row, c.name) for c in row.__table__.columns} for row in results]
