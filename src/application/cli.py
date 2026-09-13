"""Explicit local operations; no command opens a browser or submits live orders."""

import argparse
from pathlib import Path

from .operations import sqlite_backup, sqlite_ready, sqlite_restore


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
    args = parser.parse_args()
    if args.command == "backup-sqlite":
        print(sqlite_backup(args.source, args.destination))
        return 0
    if args.command == "restore-sqlite":
        print(sqlite_restore(args.backup, args.destination))
        return 0
    return 0 if sqlite_ready(args.database) else 1


if __name__ == "__main__":
    raise SystemExit(main())
