"""
Score Service - Calculates weighted composite scores from percentiles

Composite Score Formula (from Strategy1Parameters):
  final_trend_score = trend_rank*0.6 + trend_extension_rank*0.4
  final_momentum_score = momentum_rsi_rank*0.6 + momentum_ppo_rank*0.25 + momentum_ppoh_rank*0.15
  final_vol_score = rvolume_rank*0.7 + price_vol_corr_rank*0.3
  final_structure_score = structure_rank*0.5 + structure_bb_rank*0.5
  
  composite_score = trend*0.30 + momentum*0.30 + efficiency*0.20 + vol*0.15 + structure*0.05
"""

import pandas as pd
from datetime import date, timedelta

from config import setup_logger, Strategy1Parameters
from repositories import ScoreRepository, PercentileRepository

score_repo = ScoreRepository()
percentile_repo = PercentileRepository()
logger = setup_logger(name="ScoreService")


class ScoreService:
    """Service for calculating composite scores from percentiles"""
    
    def __init__(self):
        self.params = Strategy1Parameters()
    
    def _calculate_composite_for_df(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply weighted formula using factor-based percentile ranks"""
        
        # Fill NaN values in rank columns
        rank_cols = [
            'trend_rank', 'momentum_rank', 'efficiency_rank',
            'volume_rank', 'structure_rank'
        ]
        for col in rank_cols:
            if col in df.columns:
                df[col] = df[col].fillna(0).astype(float)
        
        # Composite score from factor-based ranks (30/30/20/15/5)
        df['composite_score'] = (
            self.params.trend_strength_weight * df.get('trend_rank', 0) +
            self.params.momentum_velocity_weight * df.get('momentum_rank', 0) +
            self.params.risk_efficiency_weight * df.get('efficiency_rank', 0) +
            self.params.conviction_weight * df.get('volume_rank', 0) +
            self.params.structure_weight * df.get('structure_rank', 0)
        )
        
        return df
    
    def generate_composite_scores(self):
        """
        Generate composite scores incrementally from last calculated date.
        Processes date by date for progress visibility.
        """
        logger.info("Starting incremental composite score generation...")
        
        last_score_date = score_repo.get_max_score_date()
        
        if last_score_date:
            logger.info(f"Last score date: {last_score_date}")
        else:
            logger.info("No existing scores, processing all percentiles")
        
        # Get distinct dates from percentile table to process
        from db import db
        from models import PercentileModel
        result = db.session.query(PercentileModel.percentile_date).distinct().order_by(PercentileModel.percentile_date).all()
        all_dates = [r[0] for r in result]
        
        if last_score_date:
            dates_to_process = [d for d in all_dates if d > last_score_date]
        else:
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
            
            # Convert to DataFrame
            df = pd.DataFrame([
                {c.name: getattr(r, c.name) for c in r.__table__.columns}
                for r in percentiles
            ])
            
            # Calculate composite scores
            df = self._calculate_composite_for_df(df)
            
            # Prepare records for insertion
            score_records = df[[
                'tradingsymbol', 'percentile_date',
                'trend_rank', 'momentum_rank', 
                'efficiency_rank', 'volume_rank', 'structure_rank',
                'composite_score'
            ]].copy()
            score_records.rename(columns={'percentile_date': 'score_date'}, inplace=True)
            
            # Insert into score table
            records = score_records.to_dict('records')
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