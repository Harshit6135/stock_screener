"""Explicit local operations; no command opens a browser or submits live orders."""

import argparse
from pathlib import Path

from .composition import ApplicationServices
from .kite_auth import load_kite_credentials
from .operations import sqlite_backup, sqlite_ready, sqlite_restore
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
                "KITE_API_KEY": RuntimeConfig.KITE_API_KEY,
                "KITE_API_SECRET": RuntimeConfig.KITE_API_SECRET,
            },
            profile="market_data",
        )
        job = ApplicationServices.create(
            args.data_directory,
            market_data_kite_credentials=credentials,
            market_data_kite_token_path=RuntimeConfig.MARKET_DATA_KITE_ACCESS_TOKEN_PATH,
            nse_csv_path=Path.cwd() / "data" / "imports" / "NSE.csv",
            bse_csv_path=Path.cwd() / "data" / "imports" / "BSE.csv",
            legacy_market_path=Path.cwd() / "instance" / "market_data.db",
        ).worker.run_once()
        print("idle" if job is None else f"{job.job_id}:{job.status.value}")
        return 0
    return 0 if sqlite_ready(args.database) else 1


if __name__ == "__main__":
    raise SystemExit(main())
