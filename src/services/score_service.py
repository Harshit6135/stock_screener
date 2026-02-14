"""
Score Service - Calculates weighted composite scores from percentiles
"""

import pandas as pd

from config import setup_logger, StrategyParameters
from repositories import ScoreRepository, PercentileRepository


score_repo = ScoreRepository()
percentile_repo = PercentileRepository()
logger = setup_logger(name="ScoreService")
pd.set_option('future.no_silent_downcasting', True)


class ScoreService:
    """Service for calculating composite scores from percentiles"""
    
    def __init__(self):
        self.params = StrategyParameters()
    
    def calculate_composite_scores(self, percentile_df: pd.DataFrame) -> pd.DataFrame:
        """Apply weighted formula to calculate composite scores"""
        
        percentile_df['composite_score'] = (
            self.params.trend_strength_weight * percentile_df['trend_percentile'] +
            self.params.momentum_velocity_weight * percentile_df['momentum_percentile'] +
            self.params.risk_efficiency_weight * percentile_df['efficiency_percentile'] +
            self.params.conviction_weight * percentile_df['volume_percentile'] +
            self.params.structure_weight * percentile_df['structure_percentile']
        )
        return percentile_df

    def generate_composite_scores(self):
        """
        Generate composite scores incrementally from last calculated date.
        Processes date by date for progress visibility.
        """
        logger.info("Starting incremental composite score generation...")
        
        last_score_date = score_repo.get_max_score_date()
        all_dates = percentile_repo.get_all_distinct_dates()

        if last_score_date:
            logger.info(f"Last score date: {last_score_date}")
            dates_to_process = [d for d in all_dates if d > last_score_date]
        else:
            logger.info("No existing scores, processing all percentiles")
            dates_to_process = all_dates
        
        if not dates_to_process:
            logger.info("No new dates to process")
            return {"message": "No new percentiles to process", "records": 0}
        
        logger.info(f"Processing {len(dates_to_process)} dates...")
        total_count = 0
        
        for i, percentile_date in enumerate(dates_to_process, 1):
            logger.info(f"Processing date {i}/{len(dates_to_process)}: {percentile_date}")
            
            # Get percentiles for this date
            percentiles = percentile_repo.get_percentiles_by_date(percentile_date)
            if not percentiles:
                continue
            
            percentiles_df = pd.DataFrame([
                {c.name: getattr(r, c.name) for c in r.__table__.columns}
                for r in percentiles
            ])

            scores_df = self.calculate_composite_scores(percentiles_df)
            scores_df['composite_score'] = scores_df['composite_score'] * scores_df['penalty']
            
            scores_df = scores_df[[
                'tradingsymbol', 'percentile_date',
                'composite_score'
            ]]
            scores_df.rename(columns={'percentile_date': 'score_date'}, inplace=True)
            
            records = scores_df.to_dict('records')
            result = score_repo.bulk_insert(records)
            count = len(result) if result else 0
            total_count += count
            logger.info(f"  Inserted {count} records for {percentile_date}")
        
        logger.info(f"Total: Inserted {total_count} score records")
        return {"message": f"Generated {total_count} composite scores", "records": total_count}
    
    def recalculate_all_scores(self):
        """
        Recalculate ALL composite scores from scratch.
        Use this when strategy weights have been updated.
        Processes date by date for progress visibility.
        """
        logger.info("Starting FULL score recalculation (weights may have changed)...")
        
        # Clear existing scores
        logger.info("Clearing existing score table...")
        score_repo.delete_all()
        
        # Now generate all scores
        return self.generate_composite_scores()