"""
Score Service - Calculates weighted composite scores from percentiles

Batch-processes all pending dates in a single pass using vectorised
pandas operations. Applies penalty box rules and tracks penalty
reasons for transparency.

Supports Strategy 1 (default) and Strategy 2 via strategy_id parameter.
Strategy 2 replaces global EMA soft-penalties with an ADX regime
multiplier on the Trend + Momentum buckets.
"""

import time

import pandas as pd

from config import Strategy2Parameters, StrategyParameters, setup_logger
from repositories import IndicatorsRepository, PercentileRepository, ScoreRepository

logger = setup_logger(name="ScoreService")


class ScoreService:
    """Service for calculating composite scores from percentiles"""

    def __init__(self, strategy_id: str = "strategy1"):
        self.strategy_id = strategy_id
        if strategy_id == "strategy2":
            self.params = Strategy2Parameters()
        else:
            self.params = StrategyParameters()
        self.score_repo = ScoreRepository()
        self.percentile_repo = PercentileRepository()
        self.indicators_repo = IndicatorsRepository()

    def calculate_composite_scores(self, percentile_df: pd.DataFrame) -> pd.DataFrame:
        """Apply weighted formula to calculate composite scores."""
        percentile_df["initial_composite_score"] = (
            self.params.trend_strength_weight * percentile_df["trend_percentile"]
            + self.params.momentum_velocity_weight * percentile_df["momentum_percentile"]
            + self.params.risk_efficiency_weight * percentile_df["efficiency_percentile"]
            + self.params.conviction_weight * percentile_df["volume_percentile"]
            + self.params.structure_weight * percentile_df["structure_percentile"]
        )
        return percentile_df

    # ── Strategy 1 penalty: global EMA soft multipliers ──────────────────────

    def _apply_soft_penalties(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply soft penalty multipliers using indicator data (Strategy 1).

        1. Price below 200 EMA -> * 0.5
        2. Price below 50 EMA -> * 0.7
        3. EMA 50 below min_price -> * 0.0 (Hard exclusion)
        4. Average turnover below minimum -> * 0.0 (Hard exclusion)
        """
        df["penalty_reason"] = ""
        df["penalty"] = 1.0

        mask_200 = df["ema_200"] > df["close"]
        df.loc[mask_200, "penalty_reason"] += "below_ema_200; "
        df.loc[mask_200, "penalty"] *= 0.5

        mask_50 = df["ema_50"] > df["close"]
        df.loc[mask_50, "penalty_reason"] += "below_ema_50; "
        df.loc[mask_50, "penalty"] *= 0.7

        mask_price = df["ema_50"] < self.params.min_price
        df.loc[mask_price, "penalty_reason"] += "penny_stock; "
        df.loc[mask_price, "penalty"] = 0.0

        mask_turnover = df["avg_turnover_ema_20"] < self.params.min_turnover * 10000000
        df.loc[mask_turnover, "penalty_reason"] += "low_turnover; "
        df.loc[mask_turnover, "penalty"] = 0.0

        df["penalty_reason"] = df["penalty_reason"].str.rstrip("; ")
        df["penalty_reason"] = df["penalty_reason"].replace("", None)
        return df

    # ── Strategy 2 penalty: hard exclusions only + ADX regime multiplier ─────

    def _apply_hard_exclusions(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply hard exclusions only (Strategy 2 — no global EMA soft penalties)."""
        df["penalty_reason"] = ""
        df["penalty"] = 1.0

        mask_price = df["ema_50"] < self.params.min_price
        df.loc[mask_price, "penalty_reason"] += "penny_stock; "
        df.loc[mask_price, "penalty"] = 0.0

        mask_turnover = df["avg_turnover_ema_20"] < self.params.min_turnover * 10000000
        df.loc[mask_turnover, "penalty_reason"] += "low_turnover; "
        df.loc[mask_turnover, "penalty"] = 0.0

        df["penalty_reason"] = df["penalty_reason"].str.rstrip("; ")
        df["penalty_reason"] = df["penalty_reason"].replace("", None)
        return df

    def _apply_adx_regime_multiplier(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply ADX-based regime multiplier to Trend + Momentum buckets (Strategy 2).

        Three tiers:
          ADX < 20 (choppy) → multiply T+M by 0.50
          20 ≤ ADX ≤ 30     → multiply T+M by 1.00 (neutral)
          ADX > 30 (strong) → multiply T+M by 0.90 (late-stage caution)
        """
        p = self.params  # Strategy2Parameters
        adx = df.get("adx_14", pd.Series(25.0, index=df.index)).fillna(25.0)

        multiplier = pd.Series(p.adx_neutral_multiplier, index=df.index)
        multiplier[adx < p.adx_weak_threshold] = p.adx_weak_multiplier
        multiplier[adx > p.adx_strong_threshold] = p.adx_strong_multiplier

        # Recalculate: apply multiplier only to T+M contribution, keep R+V+S unchanged
        trend_mom = (
            p.trend_strength_weight * df["trend_percentile"]
            + p.momentum_velocity_weight * df["momentum_percentile"]
        ) * multiplier

        other = (
            p.risk_efficiency_weight * df["efficiency_percentile"]
            + p.conviction_weight * df["volume_percentile"]
            + p.structure_weight * df["structure_percentile"]
        )
        df["initial_composite_score"] = trend_mom + other
        df["adx_multiplier"] = multiplier
        return df

    def generate_composite_scores(self) -> dict:
        """Generate composite scores incrementally (batch).

        Fetches all pending percentiles and indicators in single queries,
        calculates scores vectorised, and bulk-inserts the results.
        """
        try:
            t_start = time.time()
            logger.info(
                f"Starting batch composite score generation [{self.strategy_id}]..."
            )

            last_score_date = self.score_repo.get_max_score_date(
                strategy_id=self.strategy_id
            )
            if last_score_date:
                logger.info(f"Last score date [{self.strategy_id}]: {last_score_date}")

            # Step 1: Fetch strategy-specific percentiles
            t0 = time.time()
            logger.info("[1/6] Fetching percentiles from DB...")
            percentiles = self.percentile_repo.get_percentiles_after_date(
                last_score_date, strategy_id=self.strategy_id
            )
            if not percentiles:
                logger.info("No new percentiles to process")
                return {"message": "No new percentiles to process", "records": 0}
            logger.info(
                f"[1/6] Fetched {len(percentiles)} percentile rows in {time.time() - t0:.2f}s"
            )

            # Step 2: Build percentiles DataFrame
            t0 = time.time()
            logger.info("[2/6] Building percentiles DataFrame...")
            percentiles_df = pd.DataFrame(
                [{c.name: getattr(r, c.name) for c in r.__table__.columns} for r in percentiles]
            )
            n_dates = percentiles_df["percentile_date"].nunique()
            logger.info(
                f"[2/6] Built DataFrame: {len(percentiles_df)} rows, "
                f"{n_dates} dates in {time.time() - t0:.2f}s"
            )

            # Step 3: Fetch indicators (for penalty/multiplier columns)
            t0 = time.time()
            date_min = percentiles_df["percentile_date"].min()
            date_max = percentiles_df["percentile_date"].max()
            logger.info(f"[3/6] Fetching indicators ({date_min} → {date_max})...")
            indicators = self.indicators_repo.get_indicators_for_all_stocks(
                {"start_date": date_min, "end_date": date_max}
            )

            if indicators:
                indicators_df = pd.DataFrame(
                    [{c.name: getattr(r, c.name) for c in r.__table__.columns} for r in indicators]
                )
                logger.info(
                    f"[3/6] Fetched {len(indicators_df)} indicator rows in {time.time() - t0:.2f}s"
                )
            else:
                indicators_df = pd.DataFrame()
                logger.warning(
                    f"[3/6] No indicators found in {time.time() - t0:.2f}s — skipping penalties"
                )

            # Step 4: Calculate initial composite scores
            t0 = time.time()
            logger.info("[4/6] Calculating composite scores...")
            scores_df = self.calculate_composite_scores(percentiles_df)
            logger.info(f"[4/6] Scores calculated in {time.time() - t0:.2f}s")

            # Step 5: Merge indicators and apply penalties / regime multiplier
            t0 = time.time()
            logger.info("[5/6] Merging indicators & applying penalties...")
            if not indicators_df.empty:
                if self.strategy_id == "strategy2":
                    penalty_cols = [
                        "tradingsymbol", "date",
                        "ema_50", "avg_turnover_ema_20",  # hard exclusions
                        "adx_14",                          # regime multiplier
                    ]
                else:
                    penalty_cols = [
                        "tradingsymbol", "date",
                        "ema_200", "ema_50", "close",
                        "atr_spike", "avg_turnover_ema_20",
                    ]
                available_cols = [c for c in penalty_cols if c in indicators_df.columns]
                scores_df = pd.merge(
                    scores_df,
                    indicators_df[available_cols],
                    left_on=["tradingsymbol", "percentile_date"],
                    right_on=["tradingsymbol", "date"],
                    how="left",
                )

                if self.strategy_id == "strategy2":
                    scores_df = self._apply_hard_exclusions(scores_df)
                    scores_df = self._apply_adx_regime_multiplier(scores_df)
                else:
                    scores_df = self._apply_soft_penalties(scores_df)

                scores_df["composite_score"] = (
                    scores_df["initial_composite_score"] * scores_df["penalty"]
                )
                penalized = (scores_df["penalty"] < 1).sum()
                excluded = (scores_df["penalty"] == 0).sum()
                logger.info(
                    f"[5/6] Penalties applied in {time.time() - t0:.2f}s — "
                    f"{penalized} penalized, {excluded} excluded"
                )
            else:
                scores_df["penalty"] = 1
                scores_df["penalty_reason"] = None
                scores_df["composite_score"] = scores_df["initial_composite_score"]
                logger.info(f"[5/6] No penalties applied in {time.time() - t0:.2f}s")

            # Select output columns and tag with strategy_id
            out_cols = [
                "tradingsymbol", "percentile_date",
                "initial_composite_score", "penalty", "penalty_reason", "composite_score",
            ]
            scores_df = scores_df[[c for c in out_cols if c in scores_df.columns]]
            scores_df.rename(columns={"percentile_date": "score_date"}, inplace=True)
            scores_df["strategy_id"] = self.strategy_id

            # Step 6: Bulk insert
            t0 = time.time()
            logger.info(f"[6/6] Bulk inserting {len(scores_df)} score records...")
            records = scores_df.to_dict("records")
            result = self.score_repo.bulk_insert(records)
            count = len(result) if result else 0

            logger.info(
                f"[6/6] Inserted {count} records across {n_dates} dates in {time.time() - t0:.2f}s"
            )
            logger.info(
                f"Score generation complete [{self.strategy_id}] — "
                f"total elapsed: {time.time() - t_start:.2f}s"
            )
        except Exception as e:
            logger.error(f"Error generating composite scores: {e}")
            return {"message": f"Error generating composite scores: {e}", "records": 0}
        return {"message": f"Generated {count} composite scores", "records": count}

    def recalculate_all_scores(self) -> dict:
        """Recalculate ALL composite scores for this strategy from scratch."""
        logger.info(
            f"Starting FULL score recalculation [{self.strategy_id}]..."
        )
        logger.info(f"Clearing existing score table for [{self.strategy_id}]...")
        self.score_repo.delete_all(strategy_id=self.strategy_id)
        return self.generate_composite_scores()
