"""
Score Service - Calculates weighted composite scores from percentiles

Batch-processes all pending dates in a single pass using vectorised
pandas operations. Applies penalty box rules and tracks penalty
reasons for transparency.
"""

import pandas as pd

from config import setup_logger, StrategyParameters
from repositories import (
    ScoreRepository, PercentileRepository,
    IndicatorsRepository
)


score_repo = ScoreRepository()
percentile_repo = PercentileRepository()
indicators_repo = IndicatorsRepository()
logger = setup_logger(name="ScoreService")
pd.set_option('future.no_silent_downcasting', True)


class ScoreService:
    """Service for calculating composite scores from percentiles"""

    def __init__(self):
        self.params = StrategyParameters()

    def calculate_composite_scores(
        self, percentile_df: pd.DataFrame
    ) -> pd.DataFrame:
        """Apply weighted formula to calculate composite scores.

        Parameters:
            percentile_df: DataFrame with percentile columns.

        Returns:
            DataFrame with `initial_composite_score` added.

        Example:
            >>> svc = ScoreService()
            >>> df = svc.calculate_composite_scores(pct_df)
        """
        percentile_df['initial_composite_score'] = (
            self.params.trend_strength_weight
            * percentile_df['trend_percentile']
            + self.params.momentum_velocity_weight
            * percentile_df['momentum_percentile']
            + self.params.risk_efficiency_weight
            * percentile_df['efficiency_percentile']
            + self.params.conviction_weight
            * percentile_df['volume_percentile']
            + self.params.structure_weight
            * percentile_df['structure_percentile']
        )
        return percentile_df

    def _apply_universe_penalties(
        self, df: pd.DataFrame
    ) -> pd.DataFrame:
        """Apply penalty box rules using indicator data.

        Sets penalty=0 and records reason for stocks that fail
        any disqualification rule:
        1. Price below 200 EMA
        2. Price below 50 EMA
        3. ATR spike above threshold
        4. EMA 50 below min_price (proxy for penny stocks)
        5. Average turnover below minimum

        Parameters:
            df: DataFrame with indicator columns merged in.

        Returns:
            DataFrame with `penalty` and `penalty_reason` columns.

        Example:
            >>> df = svc._apply_universe_penalties(merged_df)
            >>> df[df['penalty'] == 0]['penalty_reason']
        """
        reasons = pd.Series(
            [''] * len(df), index=df.index
        )

        mask_200 = df['ema_200'] > df['close']
        reasons[mask_200] += 'below_ema_200; '

        mask_50 = df['ema_50'] > df['close']
        reasons[mask_50] += 'below_ema_50; '

        mask_atr = (
            df['atr_spike'] > self.params.atr_threshold
        )
        reasons[mask_atr] += 'atr_spike; '

        mask_price = df['ema_50'] < self.params.min_price
        reasons[mask_price] += 'penny_stock; '

        mask_turnover = (
            df['avg_turnover_ema_20']
            < self.params.min_turnover
        )
        reasons[mask_turnover] += 'low_turnover; '

        df['penalty_reason'] = reasons.str.rstrip('; ')
        df['penalty_reason'] = (
            df['penalty_reason'].replace('', None)
        )
        # penalty=0 when reason exists, penalty=1 when clean
        df['penalty'] = df['penalty_reason'].apply(
            lambda x: 0 if x else 1
        )
        return df

    def generate_composite_scores(self):
        """Generate composite scores incrementally (batch).

        Fetches all pending percentiles and indicators in
        single queries, calculates scores vectorised, and
        bulk-inserts the results.

        Returns:
            Dict with message and record count.

        Example:
            >>> result = ScoreService().generate_composite_scores()
            >>> print(result['records'])
        """
        try:
            logger.info(
                "Starting batch composite score generation..."
            )

            last_score_date = score_repo.get_max_score_date()
            if last_score_date:
                logger.info(
                    f"Last score date: {last_score_date}"
                )

            # Batch fetch: all percentiles after last score date
            percentiles = (
                percentile_repo.get_percentiles_after_date(
                    last_score_date
                )
            )
            if not percentiles:
                logger.info("No new percentiles to process")
                return {
                    "message": "No new percentiles to process",
                    "records": 0
                }

            percentiles_df = pd.DataFrame([
                {
                    c.name: getattr(r, c.name)
                    for c in r.__table__.columns
                }
                for r in percentiles
            ])
            n_dates = percentiles_df[
                'percentile_date'
            ].nunique()
            logger.info(
                f"Fetched {len(percentiles_df)} percentile "
                f"records across {n_dates} dates"
            )

            # Batch fetch: indicators for the same date range
            date_min = percentiles_df['percentile_date'].min()
            date_max = percentiles_df['percentile_date'].max()
            indicators = (
                indicators_repo.get_indicators_for_all_stocks(
                    {
                        "start_date": date_min,
                        "end_date": date_max
                    }
                )
            )

            if indicators:
                indicators_df = pd.DataFrame([
                    {
                        c.name: getattr(r, c.name)
                        for c in r.__table__.columns
                    }
                    for r in indicators
                ])
                logger.info(
                    f"Fetched {len(indicators_df)} indicator "
                    f"records for penalty checks"
                )
            else:
                indicators_df = pd.DataFrame()
                logger.warning(
                    "No indicators found — "
                    "skipping penalties"
                )

            # Calculate composite scores (vectorised)
            scores_df = self.calculate_composite_scores(
                percentiles_df
            )

            # Merge indicators and apply penalties
            if not indicators_df.empty:
                penalty_cols = [
                    'tradingsymbol', 'date',
                    'ema_200', 'ema_50',
                    'atr_spike', 'avg_turnover_ema_20'
                ]
                available_cols = [
                    c for c in penalty_cols
                    if c in indicators_df.columns
                ]
                scores_df = pd.merge(
                    scores_df,
                    indicators_df[available_cols],
                    left_on=[
                        'tradingsymbol', 'percentile_date'
                    ],
                    right_on=['tradingsymbol', 'date'],
                    how='left'
                )
                scores_df = self._apply_universe_penalties(
                    scores_df
                )
                scores_df['composite_score'] = (
                    scores_df['initial_composite_score']
                    * scores_df['penalty']
                )
            else:
                scores_df['penalty'] = 1
                scores_df['penalty_reason'] = None
                scores_df['composite_score'] = (
                    scores_df['initial_composite_score']
                )

            # Select output columns
            scores_df = scores_df[[
                'tradingsymbol', 'percentile_date',
                'initial_composite_score', 'penalty',
                'penalty_reason', 'composite_score'
            ]]
            scores_df.rename(
                columns={'percentile_date': 'score_date'},
                inplace=True
            )

            # Bulk insert all at once
            records = scores_df.to_dict('records')
            result = score_repo.bulk_insert(records)
            count = len(result) if result else 0

            logger.info(
                f"Inserted {count} score records "
                f"across {n_dates} dates (batch)"
            )
        except Exception as e:
            logger.error(f"Error generating composite scores: {e}")
            return {
                "message": f"Error generating composite scores: {e}",
                "records": 0
            }
        return {
            "message": (
                f"Generated {count} composite scores"
            ),
            "records": count
        }

    def recalculate_all_scores(self):
        """Recalculate ALL composite scores from scratch.

        Use this when strategy weights have been updated.

        Returns:
            Dict with message and record count.

        Example:
            >>> result = ScoreService().recalculate_all_scores()
        """
        logger.info(
            "Starting FULL score recalculation "
            "(weights may have changed)..."
        )

        logger.info("Clearing existing score table...")
        score_repo.delete_all()

        return self.generate_composite_scores()