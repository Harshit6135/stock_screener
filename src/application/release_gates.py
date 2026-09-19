"""Small, deterministic release-gate checks for the v3 to v4 cutover.

These checks intentionally operate on supplied snapshots and never contact a
broker or mutate a production database.  They make parity and recovery a
reviewable artifact instead of an assertion hidden in a deployment runbook.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from datetime import date
from pathlib import Path
from typing import Any

from src.application.operations import sqlite_backup, sqlite_ready, sqlite_restore
from src.platform_kernel import DomainValidationError


def next_tradable_session(signal_date: date, sessions: Iterable[date]) -> date:
    """Return the first session strictly after a signal, skipping holidays."""
    candidate = next((item for item in sorted(set(sessions)) if item > signal_date), None)
    if candidate is None:
        raise DomainValidationError("no next tradable session is available")
    return candidate


def compare_execution_events(
    v3_events: Iterable[dict[str, Any]], v4_events: Iterable[dict[str, Any]]
) -> dict[str, object]:
    """Compare execution events in order, including signal and fill times."""

    def normalize(event: dict[str, Any]) -> dict[str, str]:
        if not isinstance(event, dict):
            raise DomainValidationError("execution event must be an object")
        required = {"event", "instrument_id", "side", "units", "signal_at", "executed_at"}
        if not required.issubset(event):
            raise DomainValidationError("execution event is incomplete")
        return {key: str(event[key]) for key in sorted(required)}

    old = [normalize(item) for item in v3_events]
    new = [normalize(item) for item in v4_events]
    mismatches = [
        {"index": index, "v3": left, "v4": right}
        for index, (left, right) in enumerate(zip(old, new))
        if left != right
    ]
    if len(old) != len(new):
        mismatches.append(
            {"index": min(len(old), len(new)), "v3_count": len(old), "v4_count": len(new)}
        )
    return {
        "parity": not mismatches,
        "v3_count": len(old),
        "v4_count": len(new),
        "mismatches": mismatches,
        "read_only": True,
    }


def restore_drill(source: str | Path, workspace: str | Path) -> dict[str, object]:
    """Run a non-production backup/restore/readiness drill with digests."""
    source, workspace = Path(source), Path(workspace)
    if not source.is_file() or not sqlite_ready(source):
        raise DomainValidationError("restore drill source is not a ready SQLite database")
    workspace.mkdir(parents=True, exist_ok=True)
    backup = workspace / "cutover-backup.db"
    restored = workspace / "cutover-restored.db"
    for target in (backup, restored):
        if target.exists():
            raise DomainValidationError("restore drill destination already exists")
    sqlite_backup(source, backup)
    sqlite_restore(backup, restored)
    return {
        "source_digest": hashlib.sha256(source.read_bytes()).hexdigest(),
        "backup_digest": hashlib.sha256(backup.read_bytes()).hexdigest(),
        "restored_digest": hashlib.sha256(restored.read_bytes()).hexdigest(),
        "backup_ready": sqlite_ready(backup),
        "restored_ready": sqlite_ready(restored),
        "rollback_boundary": "new-destination-only",
        "read_only_source": True,
    }


def dashboard_visual_contract(html: str) -> dict[str, object]:
    """Validate the stable navigation/workflow contract of the dashboard."""
    required_routes = ("/app", "/actions", "/backtest", "/pipeline", "/portfolio")
    missing = [route for route in required_routes if route not in html]
    return {
        "parity": not missing,
        "required_routes": required_routes,
        "missing_routes": missing,
        "read_only": True,
    }
