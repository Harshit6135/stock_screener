"""Gate workflow for sequential, checkpointed data prerequisites."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

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
        latest_snapshot = self.market.latest_universe_snapshot("NIFTY 500")
        today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
        latest_snapshot_date = (
            date.fromisoformat(str(latest_snapshot["snapshot_date"]))
            if latest_snapshot is not None
            else None
        )
        # NIFTY 500 membership rejigs take effect at the start of April and
        # October. Fetch at most once in either month; reuse the saved snapshot
        # for every other month.
        scheduled_refresh_month = today.month in {4, 10}
        refresh_due = scheduled_refresh_month and (
            latest_snapshot_date is None
            or latest_snapshot_date.year != today.year
            or latest_snapshot_date.month != today.month
        )
        if latest_snapshot is not None and not refresh_due:
            collection = {
                "status": "reused_latest_snapshot",
                "snapshot_id": latest_snapshot["snapshot_id"],
                "snapshot_date": latest_snapshot["snapshot_date"],
                "member_count": latest_snapshot["member_count"],
            }
            context.checkpoint(
                progress={"stage": "universe_snapshot", **collection}
            )
        else:
            collection = self.universe.download_nifty500_constituents({}, context)
        snapshot_id = str(collection["snapshot_id"])
        context.checkpoint(progress={"stage": "instruments", "snapshot_id": snapshot_id})
        sync = self.market_jobs.sync_snapshot_instruments({"snapshot_id": snapshot_id}, context)
        context.checkpoint(
            progress={
                "stage": "instruments_resolved",
                "resolved_count": sync.get("resolved_count"),
                "unresolved": sync.get("unresolved", []),
            }
        )
        context.checkpoint(progress={"stage": "corporate_actions"})
        current_batch_cutoff = today - timedelta(days=7)
        if end >= current_batch_cutoff:
            batch_start = max(start, current_batch_cutoff)
            try:
                detection = self.corporate.detect_job(
                    {"start_date": batch_start.isoformat(), "as_of_date": end.isoformat()}, context
                )
                actions = self.corporate.process_actionable(
                    self.market_jobs.corporate_history,
                    context,
                    {str(event["event_id"]) for event in detection["events"]},
                )
            except DomainValidationError as exc:
                detection = {
                    "status": "unavailable_latest_batch",
                    "start_date": batch_start.isoformat(),
                    "end_date": end.isoformat(),
                    "reason": str(exc),
                }
                actions = {"status": "not_run_detection_unavailable"}
                context.checkpoint(
                    progress={
                        "stage": "corporate_actions_unavailable",
                        "start_date": batch_start.isoformat(),
                        "end_date": end.isoformat(),
                        "message": "Latest-batch corporate action source is unavailable; continuing history run.",
                    }
                )
        else:
            detection = {"status": "skipped_historical_batch", "end_date": end.isoformat()}
            actions = {"status": "skipped_historical_batch", "end_date": end.isoformat()}
            context.checkpoint(
                progress={
                    "stage": "corporate_actions_skipped",
                    "reason": "historical_batch",
                    "end_date": end.isoformat(),
                    "current_batch_cutoff": current_batch_cutoff.isoformat(),
                }
            )
        members = self.market.universe_snapshot_members(snapshot_id, limit=1000)
        isins = {row["isin"] for row in members}
        instruments = [
            row
            for row in self.market.tracked_instruments()
            if row["exchange"] == "NSE"
            and (row["isin"] in isins or row["symbol"] in NSE_INDEX_SYMBOLS)
        ]
        # The requested database begins on 2015-01-01. Later segments reuse
        # stored history from that boundary; only provider-coverage gaps are fetched.
        history_start = max(date(2015, 1, 1), start - timedelta(days=900))
        requests: dict[tuple[date, date], list[dict[str, str]]] = {}
        for row in instruments:
            instrument_id = str(row["instrument_id"])
            for missing_start, missing_end in self.market.missing_coverage_ranges(
                instrument_id, history_start, end
            ):
                cursor = missing_start
                while cursor <= missing_end:
                    chunk_end = min(missing_end, cursor + timedelta(days=1999))
                    requests.setdefault((cursor, chunk_end), []).append(
                        {"symbol": str(row["symbol"]), "exchange": str(row["exchange"])}
                    )
                    cursor = chunk_end + timedelta(days=1)
        batches = []
        for (cursor, chunk_end), items in sorted(requests.items()):
            context.checkpoint(
                progress={
                    "stage": "market_history",
                    "start_date": cursor.isoformat(),
                    "end_date": chunk_end.isoformat(),
                    "request_count": len(items),
                    "snapshot_id": snapshot_id,
                }
            )
            result = self.market_jobs.fetch_bulk_bars(
                {
                    "start_date": cursor.isoformat(),
                    "end_date": chunk_end.isoformat(),
                    "items": items,
                },
                context,
            )
            if result["failed"]:
                failed_items = [
                    {
                        "symbol": item.get("symbol"),
                        "status": item.get("status"),
                        "reason": item.get("reason"),
                    }
                    for item in result.get("results", [])
                    if item.get("status") == "error"
                ]
                context.checkpoint(
                    progress={
                        "stage": "market_history_failed",
                        "start_date": cursor.isoformat(),
                        "end_date": chunk_end.isoformat(),
                        "failed_count": result["failed"],
                        "failed_instruments": failed_items[:25],
                    }
                )
                raise DomainValidationError(
                    "market history prerequisite contains failed instruments"
                )
            batches.append(result)
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
            "snapshot_fallback": start
            < date.fromisoformat(str(collection.get("snapshot_date") or start.isoformat())),
            "collection": collection,
            "instrument_sync": {
                "resolved_count": sync.get("resolved_count"),
                "unresolved": sync.get("unresolved", []),
            },
            "corporate_detection": detection,
            "corporate_processing": actions,
            "market_batches": len(batches),
            "quality": quality,
            "indicators": indicators,
            "reconciliation": reconciliation,
        }
