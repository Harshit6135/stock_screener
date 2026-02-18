"""
Score Service - Calculates weighted composite scores from percentiles

Batch-processes all pending dates in a single pass using vectorised
pandas operations. Applies penalty box rules and tracks penalty
reasons for transparency.
"""

import time
import pandas as pd
pd.set_option('future.no_silent_downcasting', True)

from config import setup_logger, StrategyParameters
from repositories import (
    ScoreRepository, PercentileRepository,
    IndicatorsRepository
)


score_repo = ScoreRepository()
percentile_repo = PercentileRepository()
indicators_repo = IndicatorsRepository()
logger = setup_logger(name="ScoreService")


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
        """
        percentile_df['initial_composite_score'] = (
            self.params.trend_strength_weight * percentile_df['trend_percentile'] +
            self.params.momentum_velocity_weight * percentile_df['momentum_percentile'] +
            self.params.risk_efficiency_weight * percentile_df['efficiency_percentile'] +
            self.params.conviction_weight * percentile_df['volume_percentile'] +
            self.params.structure_weight * percentile_df['structure_percentile']
        )
        return percentile_df

    def _apply_soft_penalties(
        self, df: pd.DataFrame
    ) -> pd.DataFrame:
        """Apply soft penalty multipliers using indicator data.

        applies multipliers score for stocks that fail checks:
        1. Price below 200 EMA -> * 0.5
        2. Price below 50 EMA -> * 0.7
        3. ATR spike above threshold -> * 0.8
        4. EMA 50 below min_price -> * 0.0 (Hard exclusion)
        5. Average turnover below minimum -> * 0.0 (Hard exclusion)

        Parameters:
            df: DataFrame with indicator columns merged in.

        Returns:
            DataFrame with `penalty` (multiplier) and `penalty_reason` columns.
        """
        df['penalty_reason'] = ""
        df['penalty'] = 1

        mask_200 = df['ema_200'] > df['close']
        df[mask_200, 'penalty_reason'] += 'below_ema_200; '
        df[mask_200] = 0

        mask_50 = df['ema_50'] > df['close']
        df[mask_50] += 'below_ema_50; '
        df[mask_50] = 0

        mask_atr = df['atr_spike'] > self.params.atr_threshold
        df[mask_atr] += 'atr_spike; '
        df[mask_atr] = 0

        mask_price = df['ema_50'] < self.params.min_price
        df[mask_price] += 'penny_stock; '
        df[mask_price] = 0.0

        mask_turnover = df['avg_turnover_ema_20'] < self.params.min_turnover
        df[mask_turnover] += 'low_turnover; '
        df[mask_turnover] = 0.0

        df['penalty_reason'] = df['penalty_reason'].str.rstrip('; ')
        df['penalty_reason'] = df['penalty_reason'].replace('', None)
        return df

    def generate_composite_scores(self):
        """Generate composite scores incrementally (batch).

        Fetches all pending percentiles and indicators in
        single queries, calculates scores vectorised, and
        bulk-inserts the results.

        Returns:
            Dict with message and record count.
        """
        try:
            t_start = time.time()
            logger.info("Starting batch composite score generation...")

            last_score_date = score_repo.get_max_score_date()
            if last_score_date:
                logger.info(f"Last score date: {last_score_date}")

            # Step 1: Fetch percentiles
            t0 = time.time()
            logger.info("[1/6] Fetching percentiles from DB...")
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
            logger.info(
                f"[1/6] Fetched {len(percentiles)} percentile "
                f"rows in {time.time() - t0:.2f}s"
            )

            # Step 2: Build percentiles DataFrame
            t0 = time.time()
            logger.info("[2/6] Building percentiles DataFrame...")
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
                f"[2/6] Built DataFrame: {len(percentiles_df)} rows, "
                f"{n_dates} dates in {time.time() - t0:.2f}s"
            )

            # Step 3: Fetch indicators
            t0 = time.time()
            date_min = percentiles_df['percentile_date'].min()
            date_max = percentiles_df['percentile_date'].max()
            logger.info(
                f"[3/6] Fetching indicators ({date_min} → {date_max})..."
            )
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
                    f"[3/6] Fetched {len(indicators_df)} indicator "
                    f"rows in {time.time() - t0:.2f}s"
                )
            else:
                indicators_df = pd.DataFrame()
                logger.warning(
                    f"[3/6] No indicators found in {time.time() - t0:.2f}s — "
                    "skipping penalties"
                )

            # Step 4: Calculate composite scores (vectorised)
            t0 = time.time()
            logger.info("[4/6] Calculating composite scores (vector multiply)...")
            scores_df = self.calculate_composite_scores(
                percentiles_df
            )
            logger.info(
                f"[4/6] Scores calculated in {time.time() - t0:.2f}s"
            )

            # Step 5: Merge indicators and apply penalties
            t0 = time.time()
            logger.info("[5/6] Merging indicators & applying penalties...")
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
                scores_df = self._apply_soft_penalties(
                    scores_df
                )
                scores_df['composite_score'] = (
                    scores_df['initial_composite_score']
                    * scores_df['penalty']
                )
                penalized = (scores_df['penalty'] < 1).sum()
                excluded = (scores_df['penalty'] == 0).sum()
                logger.info(
                    f"[5/6] Penalties applied in {time.time() - t0:.2f}s — "
                    f"{penalized} penalized, {excluded} excluded"
                )
            else:
                scores_df['penalty'] = 1
                scores_df['penalty_reason'] = None
                scores_df['composite_score'] = (
                    scores_df['initial_composite_score']
                )
                logger.info(
                    f"[5/6] No penalties applied (no indicators) "
                    f"in {time.time() - t0:.2f}s"
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

            # Step 6: Bulk insert
            t0 = time.time()
            logger.info(f"[6/6] Bulk inserting {len(scores_df)} score records...")
            records = scores_df.to_dict('records')
            result = score_repo.bulk_insert(records)
            count = len(result) if result else 0

            logger.info(
                f"[6/6] Inserted {count} records "
                f"across {n_dates} dates in {time.time() - t0:.2f}s"
            )
            logger.info(
                f"Score generation complete — "
                f"total elapsed: {time.time() - t_start:.2f}s"
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
        """
        logger.info(
            "Starting FULL score recalculation "
            "(weights may have changed)..."
        )

        logger.info("Clearing existing score table...")
        score_repo.delete_all()

        return self.generate_composite_scores()
