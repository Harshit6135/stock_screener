from flask.views import MethodView
from flask_smorest import Blueprint

from schemas import MessageSchema, CleanupQuerySchema
from services import InitService, MarketDataService, IndicatorsService, PercentileService, ScoreService, RankingService
from repositories import MarketDataRepository, IndicatorsRepository, PercentileRepository, ScoreRepository


blp = Blueprint("App Orchestration", __name__, url_prefix="/api/v1/app", description="Application Orchestration & Cleanup Operations")


@blp.route("/cleanup")
class CleanupAfterDate(MethodView):
    @blp.doc(tags=["App Orchestration"])
    @blp.arguments(CleanupQuerySchema, location="query")
    @blp.response(200, MessageSchema)
    def delete(self, args):
        """
        Delete all data after a given start_date from:
        - marketdata
        - indicators
        - percentile
        - score
        - ranking (weekly)
        """
        start_date = args['start_date']
        
        # Initialize repositories
        marketdata_repo = MarketDataRepository()
        indicators_repo = IndicatorsRepository()
        percentile_repo = PercentileRepository()
        score_repo = ScoreRepository()
        
        # Delete data after the given date from each table
        deleted_counts = {}
        
        deleted_counts['marketdata'] = marketdata_repo.delete_after_date(start_date)
        deleted_counts['indicators'] = indicators_repo.delete_after_date(start_date)
        deleted_counts['percentile'] = percentile_repo.delete_after_date(start_date)
        deleted_counts['score'] = score_repo.delete_after_date(start_date)
        deleted_counts['ranking'] = score_repo.delete_ranking_after_date(start_date)
        
        return {
            "message": f"Deleted data after {start_date}",
            "deleted_counts": deleted_counts
        }


@blp.route("/run-pipeline")
class RunPipeline(MethodView):
    @blp.doc(tags=["App Orchestration"])
    @blp.response(200, MessageSchema)
    def post(self):
        """
        Run the full data pipeline synchronously in order:
        1. Init App (instruments setup)
        2. Update Market Data
        3. Calculate Indicators
        4. Calculate Percentiles
        5. Calculate Scores (composite)
        6. Calculate Rankings (weekly with rank column)
        """
        results = {}
        
        # Step 1: Init App
        try:
            init_service = InitService()
            init_result = init_service.initialize_app()
            results['init'] = "completed"
        except Exception as e:
            results['init'] = f"failed: {str(e)}"
        
        # Step 2: Update Market Data
        try:
            marketdata_service = MarketDataService()
            marketdata_service.update_latest_data_for_all()
            results['marketdata'] = "completed"
        except Exception as e:
            results['marketdata'] = f"failed: {str(e)}"
        
        # Step 3: Calculate Indicators
        try:
            indicators_service = IndicatorsService()
            indicators_service.calculate_indicators()
            results['indicators'] = "completed"
        except Exception as e:
            results['indicators'] = f"failed: {str(e)}"
        
        # Step 4: Calculate Percentiles
        try:
            percentile_service = PercentileService()
            percentile_service.backfill_percentiles()
            results['percentile'] = "completed"
        except Exception as e:
            results['percentile'] = f"failed: {str(e)}"
        
        # Step 5: Calculate Scores
        try:
            score_service = ScoreService()
            score_service.generate_composite_scores()
            results['score'] = "completed"
        except Exception as e:
            results['score'] = f"failed: {str(e)}"
        
        # Step 6: Calculate Rankings
        try:
            ranking_service = RankingService()
            ranking_service.generate_rankings()
            results['ranking'] = "completed"
        except Exception as e:
            results['ranking'] = f"failed: {str(e)}"
        
        return {
            "message": "Pipeline execution completed",
            "results": results
        }
