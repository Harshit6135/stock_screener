"""
Score Service - Calculates weighted composite scores and weekly averages

Composite Score Formula (from Strategy1Parameters):
  final_trend_score = trend_rank*0.6 + trend_extension_rank*0.2 + trend_start_rank*0.2
  final_momentum_score = momentum_rsi_rank*0.5 + momentum_ppo_rank*0.3 + momentum_ppoh_rank*0.2
  final_vol_score = rvolume_rank*0.7 + price_vol_corr_rank*0.3
  final_structure_score = structure_rank*0.5 + structure_bb_rank*0.5
  
  composite_score = trend*0.30 + momentum*0.25 + efficiency*0.20 + vol*0.15 + structure*0.10
"""

import pandas as pd
from datetime import date, timedelta

from config import setup_logger, Strategy1Parameters
from repositories import ScoreRepository

score_repo = ScoreRepository()
logger = setup_logger(name="ScoreService")


def get_friday(d):
    """Get the Friday of the week containing date d (Friday = weekday 4)"""
    days_until_friday = (4 - d.weekday()) % 7
    if d.weekday() > 4:  # If Saturday or Sunday, go to previous Friday
        days_until_friday = d.weekday() - 4
        return d - timedelta(days=days_until_friday)
    return d + timedelta(days=days_until_friday)


class ScoreService:
    """Service for calculating composite scores and weekly averages"""
    
    def __init__(self):
        self.params = Strategy1Parameters()
    
    def _calculate_composite_for_df(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply weighted formula to calculate composite scores"""
        
        # Fill NaN values in rank columns to avoid FutureWarning
        rank_cols = [
            'trend_rank', 'trend_extension_rank', 'trend_start_rank',
            'momentum_rsi_rank', 'momentum_ppo_rank', 'momentum_ppoh_rank',
            'rvolume_rank', 'price_vol_corr_rank',
            'structure_rank', 'structure_bb_rank', 'efficiency_rank'
        ]
        for col in rank_cols:
            if col in df.columns:
                df[col] = df[col].fillna(0).astype(float)
        
        # Calculate component scores
        df['final_trend_score'] = (
            df['trend_rank'] * self.params.trend_rank_weight +
            df['trend_extension_rank'] * self.params.trend_extension_rank_weight +
            df['trend_start_rank'] * self.params.trend_start_rank_weight
        )
        
        df['final_momentum_score'] = (
            df['momentum_rsi_rank'] * self.params.momentum_rsi_rank_weight +
            df['momentum_ppo_rank'] * self.params.momentum_ppo_rank_weight +
            df['momentum_ppoh_rank'] * self.params.momentum_ppoh_rank_weight
        )
        
        df['final_vol_score'] = (
            df['rvolume_rank'] * self.params.rvolume_rank_weight +
            df['price_vol_corr_rank'] * self.params.price_vol_corr_rank_weight
        )
        
        df['final_structure_score'] = (
            df['structure_rank'] * self.params.structure_rank_weight +
            df['structure_bb_rank'] * self.params.structure_bb_rank_weight
        )
        
        # Calculate composite score
        df['composite_score'] = (
            self.params.trend_strength_weight * df['final_trend_score'] +
            self.params.momentum_velocity_weight * df['final_momentum_score'] +
            self.params.risk_efficiency_weight * df['efficiency_rank'] +
            self.params.conviction_weight * df['final_vol_score'] +
            self.params.structure_weight * df['final_structure_score']
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
            logger.info("No existing scores, processing all rankings")
        
        # Get distinct dates to process
        all_dates = score_repo.get_distinct_ranking_dates()
        if last_score_date:
            dates_to_process = [d for d in all_dates if d > last_score_date]
        else:
            dates_to_process = all_dates
        
        if not dates_to_process:
            logger.info("No new dates to process")
            return {"message": "No new rankings to process", "records": 0}
        
        logger.info(f"Processing {len(dates_to_process)} dates...")
        total_count = 0
        
        for i, ranking_date in enumerate(dates_to_process, 1):
            logger.info(f"Processing date {i}/{len(dates_to_process)}: {ranking_date}")
            
            # Get rankings for this date
            rankings = score_repo.get_rankings_by_date(ranking_date)
            if not rankings:
                continue
            
            # Convert to DataFrame
            df = pd.DataFrame([
                {c.name: getattr(r, c.name) for c in r.__table__.columns}
                for r in rankings
            ])
            
            # Calculate composite scores
            df = self._calculate_composite_for_df(df)
            
            # Prepare records for insertion
            score_records = df[[
                'tradingsymbol', 'ranking_date',
                'final_trend_score', 'final_momentum_score', 
                'final_vol_score', 'final_structure_score',
                'composite_score'
            ]].copy()
            score_records.rename(columns={'ranking_date': 'score_date'}, inplace=True)
            
            # Insert into score table
            records = score_records.to_dict('records')
            result = score_repo.bulk_insert(records)
            count = len(result) if result else 0
            total_count += count
            logger.info(f"  Inserted {count} records for {ranking_date}")
        
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
        
        # Get all distinct dates
        dates_to_process = score_repo.get_distinct_ranking_dates()
        if not dates_to_process:
            logger.info("No rankings found")
            return {"message": "No rankings to process", "records": 0}
        
        logger.info(f"Processing {len(dates_to_process)} dates...")
        total_count = 0
        
        for i, ranking_date in enumerate(dates_to_process, 1):
            logger.info(f"Processing date {i}/{len(dates_to_process)}: {ranking_date}")
            
            # Get rankings for this date
            rankings = score_repo.get_rankings_by_date(ranking_date)
            if not rankings:
                continue
            
            # Convert to DataFrame
            df = pd.DataFrame([
                {c.name: getattr(r, c.name) for c in r.__table__.columns}
                for r in rankings
            ])
            
            # Calculate composite scores
            df = self._calculate_composite_for_df(df)
            
            # Prepare records for insertion
            score_records = df[[
                'tradingsymbol', 'ranking_date',
                'final_trend_score', 'final_momentum_score', 
                'final_vol_score', 'final_structure_score',
                'composite_score'
            ]].copy()
            score_records.rename(columns={'ranking_date': 'score_date'}, inplace=True)
            
            # Insert into score table
            records = score_records.to_dict('records')
            result = score_repo.bulk_insert(records)
            count = len(result) if result else 0
            total_count += count
            logger.info(f"  Inserted {count} records for {ranking_date}")
        
        logger.info(f"Total: Recalculated {total_count} score records")
        return {"message": f"Recalculated {total_count} composite scores", "records": total_count}
    
    def generate_avg_scores(self):
        """
        Generate weekly average scores incrementally.
        For each Friday, calculate average of that week's (Mon-Fri) daily scores.
        """
        logger.info("Starting incremental avg score generation...")
        
        last_avg_date = score_repo.get_max_avg_score_date()
        last_score_date = score_repo.get_max_score_date()
        
        if not last_score_date:
            logger.info("No scores available for averaging")
            return {"message": "No scores available", "weeks": 0}
        
        # Determine starting Friday
        if last_avg_date:
            current_friday = get_friday(last_avg_date) + timedelta(days=7)
        else:
            # Start from first available Friday after earliest score
            distinct_dates = score_repo.get_distinct_ranking_dates()
            if not distinct_dates:
                return {"message": "No score dates available", "weeks": 0}
            first_date = distinct_dates[0]
            current_friday = get_friday(first_date)
            if current_friday < first_date:
                current_friday += timedelta(days=7)
        
        # End at latest score date's Friday
        end_friday = get_friday(last_score_date)
        
        weeks_processed = 0
        all_avg_records = []
        
        while current_friday <= end_friday:
            # Week range: Monday to Friday (inclusive)
            week_monday = current_friday - timedelta(days=4)  # Friday - 4 = Monday
            week_friday = current_friday
            
            # Get scores for this week (Mon-Fri inclusive)
            scores = score_repo.get_scores_in_date_range(week_monday, week_friday)
            
            if scores:
                df = pd.DataFrame([
                    {'tradingsymbol': s.tradingsymbol, 'composite_score': s.composite_score}
                    for s in scores
                ])
                
                # Calculate average per symbol
                weekly_avg = df.groupby('tradingsymbol')['composite_score'].mean().reset_index()
                weekly_avg['score_date'] = current_friday  # Store as Friday's date
                
                all_avg_records.extend(weekly_avg.to_dict('records'))
                weeks_processed += 1
                logger.info(f"Processed week ending {current_friday}")
            
            current_friday += timedelta(days=7)
        
        if all_avg_records:
            score_repo.bulk_insert_avg(all_avg_records)
        
        logger.info(f"Generated avg scores for {weeks_processed} weeks")
        return {"message": f"Generated avg scores for {weeks_processed} weeks", "weeks": weeks_processed}
    
    def recalculate_all_avg_scores(self):
        """
        Recalculate ALL weekly average scores from scratch.
        Use this when composite scores have been recalculated.
        """
        logger.info("Starting FULL avg score recalculation...")
        
        # Clear existing avg scores
        logger.info("Clearing existing avg_score table...")
        score_repo.delete_all_avg()
        
        # Now generate all avg scores
        return self.generate_avg_scores()