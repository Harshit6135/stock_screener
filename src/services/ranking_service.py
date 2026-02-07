"""
Ranking Service - Calculates weekly rankings from daily scores

For each Friday, calculate average of that week's (Mon-Fri) daily scores,
sort by score descending, and assign rank (1 = highest).
"""

import pandas as pd
from datetime import date, timedelta

from config import setup_logger
from repositories import ScoreRepository

score_repo = ScoreRepository()
logger = setup_logger(name="RankingService")


def get_friday(d):
    """Get the Friday of the week containing date d (Friday = weekday 4)"""
    days_until_friday = (4 - d.weekday()) % 7
    if d.weekday() > 4:  # If Saturday or Sunday, go to previous Friday
        days_until_friday = d.weekday() - 4
        return d - timedelta(days=days_until_friday)
    return d + timedelta(days=days_until_friday)


class RankingService:
    """Service for calculating weekly rankings from daily scores"""
    
    def generate_rankings(self):
        """
        Generate weekly rankings incrementally.
        For each Friday, calculate average of that week's (Mon-Fri) daily scores,
        sort by score descending, and assign rank (1 = highest).
        """
        logger.info("Starting incremental ranking generation...")
        
        last_ranking_date = score_repo.get_max_ranking_date()
        last_score_date = score_repo.get_max_score_date()
        
        if not last_score_date:
            logger.info("No scores available for ranking")
            return {"message": "No scores available", "weeks": 0}
        
        # Determine starting Friday
        if last_ranking_date:
            current_friday = get_friday(last_ranking_date) + timedelta(days=7)
        else:
            # Start from first available Friday after earliest score
            from db import db
            from models import ScoreModel
            result = db.session.query(ScoreModel.score_date).distinct().order_by(ScoreModel.score_date).all()
            distinct_dates = [r[0] for r in result]
            if not distinct_dates:
                return {"message": "No score dates available", "weeks": 0}
            first_date = distinct_dates[0]
            current_friday = get_friday(first_date)
            if current_friday < first_date:
                current_friday += timedelta(days=7)
        
        # End at latest score date's Friday
        end_friday = get_friday(last_score_date)
        weeks_processed = 0
        all_ranking_records = []
        
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
                
                # Sort by composite_score descending and assign rank
                weekly_avg = weekly_avg.sort_values('composite_score', ascending=False).reset_index(drop=True)
                weekly_avg['rank'] = range(1, len(weekly_avg) + 1)
                weekly_avg['ranking_date'] = current_friday  # Store as Friday's date
                
                all_ranking_records.extend(weekly_avg.to_dict('records'))
                weeks_processed += 1
                logger.info(f"Processed week ending {current_friday}")
            
            current_friday += timedelta(days=7)
        
        if all_ranking_records:
            score_repo.bulk_insert_ranking(all_ranking_records)
        
        logger.info(f"Generated rankings for {weeks_processed} weeks")
        return {"message": f"Generated rankings for {weeks_processed} weeks", "weeks": weeks_processed}
    
    def recalculate_all_rankings(self):
        """
        Recalculate ALL weekly rankings from scratch.
        Use this when composite scores have been recalculated.
        """
        logger.info("Starting FULL ranking recalculation...")
        
        # Clear existing rankings
        logger.info("Clearing existing ranking table...")
        score_repo.delete_all_ranking()
        
        # Now generate all rankings
        return self.generate_rankings()
