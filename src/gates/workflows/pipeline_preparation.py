"""Gate workflow for sequential, checkpointed data prerequisites."""

from datetime import date, timedelta

from src.domains.market_data import NSE_INDEX_SYMBOLS
from src.gates.session_coverage import CompletedSessionCoverage
from src.platform_kernel import DomainValidationError


class PipelinePreparation:
    def __init__(self, universe, market, market_jobs, corporate, research, refresh, accounts):
        self.universe, self.market, self.market_jobs = universe, market, market_jobs
        self.corporate, self.research, self.refresh, self.accounts = (
            corporate,
            research,
            refresh,
            accounts,
        )

    def run(self, payload, context):
        start, end = (
            date.fromisoformat(payload["start_date"]),
            date.fromisoformat(payload["end_date"]),
        )
        context.checkpoint(
            progress={"stage": "universe", "message": "Collecting immutable NSE membership"}
        )
        collection = self.universe.download_nifty500_constituents({}, context)
        snapshot = self.market.universe_snapshot_as_of("NIFTY 500", end)
        snapshot_id = str(snapshot["snapshot_id"])
        context.checkpoint(progress={"stage": "instruments", "snapshot_id": snapshot_id})
        sync = self.market_jobs.sync_snapshot_instruments({"snapshot_id": snapshot_id}, context)
        if sync.get("unresolved"):
            raise DomainValidationError("snapshot instrument resolution is incomplete")
        context.checkpoint(progress={"stage": "corporate_actions"})
        detection = self.corporate.detect_job({"as_of_date": end.isoformat()}, context)
        actions = self.corporate.process_actionable(self.market_jobs.corporate_history, context)
        members = self.market.universe_snapshot_members(snapshot_id, limit=1000)
        isins = {row["isin"] for row in members}
        instruments = [
            row
            for row in self.market.tracked_instruments()
            if row["exchange"] == "NSE"
            and (row["isin"] in isins or row["symbol"] in NSE_INDEX_SYMBOLS)
        ]
        # Full warm-up for newly tracked members; provider coverage handles reuse.
        cursor = min(start - timedelta(days=900), date(2021, 1, 1))
        batches = []
        while cursor <= end:
            chunk_end = min(end, cursor + timedelta(days=364))
            context.checkpoint(
                progress={
                    "stage": "market_history",
                    "start_date": cursor.isoformat(),
                    "end_date": chunk_end.isoformat(),
                    "snapshot_id": snapshot_id,
                }
            )
            result = self.market_jobs.fetch_bulk_bars(
                {
                    "start_date": cursor.isoformat(),
                    "end_date": chunk_end.isoformat(),
                    "items": [{"symbol": row["symbol"], "exchange": "NSE"} for row in instruments],
                },
                context,
            )
            if result["failed"]:
                raise DomainValidationError(
                    "market history prerequisite contains failed instruments"
                )
            batches.append(result)
            cursor = chunk_end + timedelta(days=1)
        context.checkpoint(
            progress={
                "stage": "quality",
                "snapshot_id": snapshot_id,
                "message": "Checking completed benchmark sessions against historical membership",
            }
        )
        quality = CompletedSessionCoverage(self.market, NSE_INDEX_SYMBOLS).record(start, end)
        context.checkpoint(progress={"stage": "indicators", "snapshot_id": snapshot_id})
        indicators = self.research.rebuild_indicators(
            {"start_date": start.isoformat(), "end_date": end.isoformat()}, context
        )
        reconciliation = self.refresh.reconcile(
            {
                "as_of_date": end.isoformat(),
                "start_date": start.isoformat(),
                "source_instruments": members,
            }
        )
        return {
            "snapshot_id": snapshot_id,
            "snapshot_fallback": snapshot.get("earliest_fallback", False),
            "collection": collection,
            "corporate_detection": detection,
            "corporate_processing": actions,
            "market_batches": len(batches),
            "quality": quality,
            "indicators": indicators,
            "reconciliation": reconciliation,
        }
