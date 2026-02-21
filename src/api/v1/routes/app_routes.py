from flask.views import MethodView
from flask_smorest import Blueprint
import traceback

from schemas import (
    MessageSchema,
    CleanupQuerySchema,
    PipelineQuerySchema,
    RecalculateQuerySchema,
)
from services import (
    InitService,
    MarketDataService,
    IndicatorsService,
    PercentileService,
    ScoreService,
    RankingService,
)
from repositories import (
    MarketDataRepository,
    IndicatorsRepository,
    PercentileRepository,
    ScoreRepository,
    RankingRepository,
)


blp = Blueprint(
    "App Orchestration",
    __name__,
    url_prefix="/api/v1/app",
    description="Application Orchestration & Cleanup Operations",
)


@blp.route("/cleanup")
class CleanupAfterDate(MethodView):
    @blp.doc(tags=["App Orchestration"])
    @blp.arguments(CleanupQuerySchema, location="query")
    @blp.response(200, MessageSchema)
    def delete(self, args):
        """Delete data after a given start_date from selected tables.

        Toggle individual tables via boolean query params.
        All default to true (delete from all tables).
        """
        start_date = args['start_date']
        deleted_counts = {}

        if args.get('marketdata', True):
            repo = MarketDataRepository()
            deleted_counts['marketdata'] = repo.delete_after_date(
                start_date
            )

        if args.get('indicators', True):
            repo = IndicatorsRepository()
            deleted_counts['indicators'] = repo.delete_after_date(
                start_date
            )

        if args.get('percentile', True):
            repo = PercentileRepository()
            deleted_counts['percentile'] = repo.delete_after_date(
                start_date
            )

        if args.get('score', True):
            repo = ScoreRepository()
            deleted_counts['score'] = repo.delete_after_date(
                start_date
            )

        if args.get('ranking', True):
            repo = RankingRepository()
            deleted_counts['ranking'] = repo.delete_after_date(
                start_date
            )

        return {
            "message": f"Deleted data after {start_date}",
            "deleted_counts": deleted_counts,
        }


@blp.route("/run-pipeline")
class RunPipeline(MethodView):
    @blp.doc(tags=["App Orchestration"])
    @blp.arguments(PipelineQuerySchema, location="json")
    @blp.response(200, MessageSchema)
    def post(self, args):
        """Run the data pipeline with selectable steps.

        Toggle individual steps via boolean JSON body params.
        All default to true (run full pipeline).

        Pipeline order:
        1. Init App (instruments setup)
        2. Update Market Data
        3. Calculate Indicators
        4. Calculate Percentiles
        5. Calculate Scores (composite)
        6. Calculate Rankings (weekly with rank column)
        """
        results = {}

        # Step 1: Init App
        if args.get('init', True):
            try:
                init_service = InitService()
                init_service.initialize_app()
                results['init'] = "completed"
            except Exception as e:
                traceback.print_exc()
                results['init'] = f"failed: {str(e)}"

        # Step 2: Update Market Data
        if args.get('marketdata', True):
            try:
                marketdata_service = MarketDataService()
                historical = args.get('historical', False)
                marketdata_service.update_latest_data_for_all(
                    historical=historical
                )
                results['marketdata'] = "completed"
            except Exception as e:
                traceback.print_exc()
                results['marketdata'] = f"failed: {str(e)}"

        # Step 3: Calculate Indicators
        if args.get('indicators', True):
            try:
                indicators_service = IndicatorsService()
                indicators_service.calculate_indicators()
                results['indicators'] = "completed"
            except Exception as e:
                traceback.print_exc()
                results['indicators'] = f"failed: {str(e)}"

        # Step 4: Calculate Percentiles
        if args.get('percentile', True):
            try:
                percentile_service = PercentileService()
                percentile_service.backfill_percentiles()
                results['percentile'] = "completed"
            except Exception as e:
                traceback.print_exc()
                results['percentile'] = f"failed: {str(e)}"

        # Step 5: Calculate Scores
        if args.get('score', True):
            try:
                score_service = ScoreService()
                score_service.generate_composite_scores()
                results['score'] = "completed"
            except Exception as e:
                traceback.print_exc()
                results['score'] = f"failed: {str(e)}"

        # Step 6: Calculate Rankings
        if args.get('ranking', True):
            try:
                ranking_service = RankingService()
                ranking_service.generate_rankings()
                results['ranking'] = "completed"
            except Exception as e:
                traceback.print_exc()
                results['ranking'] = f"failed: {str(e)}"

        return {
            "message": "Pipeline execution completed",
            "results": results,
        }


@blp.route("/recalculate")
class RecalculateFromDate(MethodView):
    @blp.doc(tags=["App Orchestration"])
    @blp.arguments(RecalculateQuerySchema, location="query")
    @blp.response(200, MessageSchema)
    def post(self, args):
        """Recalculate downstream data from a given start_date.

        Deletes existing data >= start_date for enabled tables,
        then regenerates in dependency order:
        percentile -> score -> ranking.

        Toggle individual tables via boolean query params.
        All default to true.
        """
        start_date = args['start_date']
        results = {}

        # Percentile: delete + regenerate
        if args.get('percentile', True):
            try:
                percentile_repo = PercentileRepository()
                deleted = percentile_repo.delete_after_date(start_date)
                results['percentile_deleted'] = deleted

                percentile_service = PercentileService()
                percentile_service.backfill_percentiles()
                results['percentile'] = "recalculated"
            except Exception as e:
                results['percentile'] = f"failed: {str(e)}"

        # Score: delete + regenerate
        if args.get('score', True):
            try:
                score_repo = ScoreRepository()
                deleted = score_repo.delete_after_date(start_date)
                results['score_deleted'] = deleted

                score_service = ScoreService()
                score_service.generate_composite_scores()
                results['score'] = "recalculated"
            except Exception as e:
                results['score'] = f"failed: {str(e)}"

        # Ranking: delete + regenerate
        if args.get('ranking', True):
            try:
                ranking_repo = RankingRepository()
                deleted = ranking_repo.delete_after_date(start_date)
                results['ranking_deleted'] = deleted

                ranking_service = RankingService()
                ranking_service.generate_rankings()
                results['ranking'] = "recalculated"
            except Exception as e:
                results['ranking'] = f"failed: {str(e)}"

        return {
            "message": (
                f"Recalculation from {start_date} completed"
            ),
            "results": results,
        }
