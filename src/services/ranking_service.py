"""
Ranking Service - Calculates weekly rankings from daily scores

For each Friday, calculate average of that week's (Mon-Fri) daily scores,
sort by score descending, and assign rank (1 = highest).
"""

import pandas as pd
from datetime import date, timedelta

from config import setup_logger
from repositories import ScoreRepository, RankingRepository


score_repo = ScoreRepository()
ranking_repo = RankingRepository()
logger = setup_logger(name="RankingService")
pd.set_option('future.no_silent_downcasting', True)


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

        Incomplete week guard: skips a week if today <= that Friday,
        because T-1 pipeline means Friday's data isn't ready until
        Saturday at the earliest. If Friday is a holiday the week is
        still considered complete once Saturday arrives — we simply
        average whatever trading-day scores exist in Mon-Fri range.
        """
        logger.info("Starting incremental ranking generation...")
        
        last_ranking_date = ranking_repo.get_max_ranking_date()
        last_score_date = score_repo.get_max_score_date()
        
        if not last_score_date:
            logger.info("No scores available for ranking")
            return {"message": "No scores available", "weeks": 0}
        
        # Determine starting Friday
        if last_ranking_date:
            current_friday = get_friday(last_ranking_date) + timedelta(days=7)
        else:
            # Start from first available Friday after earliest score
            distinct_dates = score_repo.get_all_distinct_dates()
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
        today = date.today()
        
        while current_friday <= end_friday:
            # Skip incomplete weeks — don't rank until we're past Friday
            # Handles T-1 lag: running ON Friday only has data up to Thu
            # Handles holidays: once Saturday arrives, use available days
            friday_as_date = (
                current_friday.date()
                if hasattr(current_friday, 'date')
                else current_friday
            )
            if friday_as_date >= today:
                logger.info(
                    f"Skipping week ending {current_friday} — "
                    f"week not yet complete (today={today})"
                )
                current_friday += timedelta(days=7)
                continue

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
            ranking_repo.bulk_insert(all_ranking_records)
        
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
        ranking_repo.delete_all()
        
        # Now generate all rankings
        return self.generate_rankings()
