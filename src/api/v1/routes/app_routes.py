from flask import Response, stream_with_context
from flask.views import MethodView
from flask_smorest import Blueprint
import traceback

from adaptors import KiteAdaptor
from config import setup_logger, KITE_CONFIG, sse_log_queue
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

logger = setup_logger(name='Orchestrator')



blp = Blueprint(
    "App Orchestration",
    __name__,
    url_prefix="/api/v1/app",
    description="Application Orchestration & Cleanup Operations",
)


@blp.route("/logs/stream")
class LogStream(MethodView):
    def get(self):
        """SSE stream of Orchestrator log lines. Open before running the pipeline."""
        def _generate():
            import queue as _queue
            while True:
                try:
                    msg = sse_log_queue.get(timeout=30)
                    # Escape newlines so SSE stays single-line per event
                    safe = msg.replace('\n', ' ').replace('\r', '')
                    yield f"data: {safe}\n\n"
                except _queue.Empty:
                    # Keep-alive ping every 30 s so the browser doesn't time out
                    yield "data: [PING]\n\n"

        return Response(
            stream_with_context(_generate()),
            mimetype='text/event-stream',
            headers={
                'Cache-Control': 'no-cache',
                'X-Accel-Buffering': 'no',     # disable nginx buffering
            }
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
        failed = False
        batch_size = args.get("yfinance_batch_size", 100)
        sleep_time = args.get("yfinance_sleep_time", 4)

        # Step 0: Kite Authentication
        # Validates the stored access token (or triggers a fresh login) before
        # any downstream step that calls the Kite API.
        try:
            kite_client = KiteAdaptor(KITE_CONFIG, logger)
            # _initialize_kite → _ensure_session → kite.profile() is called inside
            # the constructor.  If the token is invalid it triggers the login flow.
            # If the constructor raises, we treat it as an auth failure.
            if kite_client.kite is None:
                raise RuntimeError("Kite client failed to initialise (check API key / credentials).")
            results['kite_auth'] = "completed"
        except Exception as e:
            traceback.print_exc()
            results['kite_auth'] = f"failed: {str(e)}"
            failed = True

        # Step 1: Init App
        if args.get('init', True):
            if failed:
                results['init'] = "skipped (previous step failed)"
            else:
                try:
                    init_service = InitService()
                    init_service.initialize_app(batch_size=batch_size, sleep_time=sleep_time)
                    results['init'] = "completed"
                except Exception as e:
                    traceback.print_exc()
                    results['init'] = f"failed: {str(e)}"
                    failed = True

        # Step 2: Update Market Data
        if args.get('marketdata', True):
            if failed:
                results['marketdata'] = "skipped (previous step failed)"
            else:
                try:
                    marketdata_service = MarketDataService()
                    historical = args.get('historical', False)
                    marketdata_service.update_latest_data_for_all(historical=historical)
                    results['marketdata'] = "completed"
                except Exception as e:
                    traceback.print_exc()
                    results['marketdata'] = f"failed: {str(e)}"
                    failed = True

        # Step 3: Calculate Indicators
        if args.get('indicators', True):
            if failed:
                results['indicators'] = "skipped (previous step failed)"
            else:
                try:
                    indicators_service = IndicatorsService()
                    indicators_service.calculate_indicators()
                    results['indicators'] = "completed"
                except Exception as e:
                    traceback.print_exc()
                    results['indicators'] = f"failed: {str(e)}"
                    failed = True

        # Step 4: Calculate Percentiles
        if args.get('percentile', True):
            if failed:
                results['percentile'] = "skipped (previous step failed)"
            else:
                try:
                    percentile_service = PercentileService()
                    percentile_service.backfill_percentiles()
                    results['percentile'] = "completed"
                except Exception as e:
                    traceback.print_exc()
                    results['percentile'] = f"failed: {str(e)}"
                    failed = True

        # Step 5: Calculate Scores
        if args.get('score', True):
            if failed:
                results['score'] = "skipped (previous step failed)"
            else:
                try:
                    score_service = ScoreService()
                    score_service.generate_composite_scores()
                    results['score'] = "completed"
                except Exception as e:
                    traceback.print_exc()
                    results['score'] = f"failed: {str(e)}"
                    failed = True

        # Step 6: Calculate Rankings
        if args.get('ranking', True):
            if failed:
                results['ranking'] = "skipped (previous step failed)"
            else:
                try:
                    ranking_service = RankingService()
                    ranking_service.generate_rankings()
                    results['ranking'] = "completed"
                except Exception as e:
                    traceback.print_exc()
                    results['ranking'] = f"failed: {str(e)}"
                    failed = True

        return {
            "message": "Pipeline aborted due to a step failure" if failed else "Pipeline execution completed",
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
        failed = False

        # Percentile: delete + regenerate
        if args.get('percentile', True):
            if failed:
                results['percentile'] = "skipped (previous step failed)"
            else:
                try:
                    percentile_repo = PercentileRepository()
                    deleted = percentile_repo.delete_after_date(start_date)
                    results['percentile_deleted'] = deleted

                    percentile_service = PercentileService()
                    percentile_service.backfill_percentiles()
                    results['percentile'] = "recalculated"
                except Exception as e:
                    results['percentile'] = f"failed: {str(e)}"
                    failed = True

        # Score: delete + regenerate
        if args.get('score', True):
            if failed:
                results['score'] = "skipped (previous step failed)"
            else:
                try:
                    score_repo = ScoreRepository()
                    deleted = score_repo.delete_after_date(start_date)
                    results['score_deleted'] = deleted

                    score_service = ScoreService()
                    score_service.generate_composite_scores()
                    results['score'] = "recalculated"
                except Exception as e:
                    results['score'] = f"failed: {str(e)}"
                    failed = True

        # Ranking: delete + regenerate
        if args.get('ranking', True):
            if failed:
                results['ranking'] = "skipped (previous step failed)"
            else:
                try:
                    ranking_repo = RankingRepository()
                    deleted = ranking_repo.delete_after_date(start_date)
                    results['ranking_deleted'] = deleted

                    ranking_service = RankingService()
                    ranking_service.generate_rankings()
                    results['ranking'] = "recalculated"
                except Exception as e:
                    results['ranking'] = f"failed: {str(e)}"
                    failed = True

        return {
            "message": (
                f"Recalculation from {start_date} aborted due to a step failure"
                if failed else
                f"Recalculation from {start_date} completed"
            ),
            "results": results,
        }
