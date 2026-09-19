"""Explicit local operations; no command opens a browser or submits live orders."""

import argparse
import json
from pathlib import Path

from .composition import ApplicationServices
from .index_poller import IndexQuotePoller
from .intraday_stream import IntradayStreamLease
from .jobs import JobStore
from .kite_auth import load_kite_credentials
from .operations import sqlite_backup, sqlite_ready, sqlite_restore
from .pipeline_jobs import ResearchPipelineJobs
from .runtime import RuntimeConfig


def main() -> int:
    parser = argparse.ArgumentParser(prog="screener-ops")
    subparsers = parser.add_subparsers(dest="command", required=True)
    backup = subparsers.add_parser("backup-sqlite")
    backup.add_argument("source", type=Path)
    backup.add_argument("destination", type=Path)
    restore = subparsers.add_parser("restore-sqlite")
    restore.add_argument("backup", type=Path)
    restore.add_argument("destination", type=Path)
    ready = subparsers.add_parser("check-sqlite")
    ready.add_argument("database", type=Path)
    worker = subparsers.add_parser("work-once")
    worker.add_argument("data_directory", type=Path)
    pipeline_status = subparsers.add_parser("pipeline-status")
    pipeline_status.add_argument("database", type=Path)
    pipeline_status.add_argument("pipeline_id")
    poller_state = subparsers.add_parser("poller-state")
    poller_state.add_argument("database", type=Path)
    poller_state.add_argument("--reconcile", action="store_true")
    stream_state = subparsers.add_parser("stream-state")
    stream_state.add_argument("database", type=Path)
    stream_action = stream_state.add_mutually_exclusive_group()
    stream_action.add_argument("--start-account")
    stream_action.add_argument("--stop", action="store_true")
    stream_state.add_argument("--token-count", type=int, default=0)
    stream_state.add_argument("--heartbeat", action="store_true")
    args = parser.parse_args()
    if args.command == "backup-sqlite":
        print(sqlite_backup(args.source, args.destination))
        return 0
    if args.command == "restore-sqlite":
        print(sqlite_restore(args.backup, args.destination))
        return 0
    if args.command == "work-once":
        credentials = load_kite_credentials(
            {
                "MARKET_DATA_KITE_API_KEY": RuntimeConfig.MARKET_DATA_KITE_API_KEY,
                "MARKET_DATA_KITE_API_SECRET": RuntimeConfig.MARKET_DATA_KITE_API_SECRET,
            },
            profile="market_data",
        )
        job = ApplicationServices.create(
            args.data_directory,
            market_data_kite_credentials=credentials,
            market_data_kite_token_path=RuntimeConfig.MARKET_DATA_KITE_ACCESS_TOKEN_PATH,
            nse_csv_path=Path.cwd() / "data" / "imports" / "NSE.csv",
            bse_csv_path=Path.cwd() / "data" / "imports" / "BSE.csv",
        ).worker.run_once()
        print("idle" if job is None else f"{job.job_id}:{job.status.value}")
        return 0
    if args.command == "pipeline-status":
        result = ResearchPipelineJobs(args.database, JobStore(args.database)).status(args.pipeline_id)
        print(json.dumps(result, sort_keys=True))
        return 0
    if args.command == "poller-state":
        jobs = JobStore(args.database)
        poller = IndexQuotePoller(args.database, jobs)
        result = poller.reconcile() if args.reconcile else poller.state()
        print(json.dumps(result, default=str, sort_keys=True))
        return 0
    if args.command == "stream-state":
        stream = IntradayStreamLease(args.database)
        if args.start_account is not None:
            if args.token_count == 0:
                parser.error("--token-count is required with --start-account")
            result = stream.start(args.start_account, args.token_count)
        elif args.stop:
            result = stream.stop()
        elif args.heartbeat:
            result = stream.heartbeat()
        else:
            result = stream.state()
        print(json.dumps(result, default=str, sort_keys=True))
        return 0
    return 0 if sqlite_ready(args.database) else 1


if __name__ == "__main__":
    raise SystemExit(main())
