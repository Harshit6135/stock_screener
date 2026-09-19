"""Immutable declarative strategy definitions.

YAML is an import/export format.  Normalised JSON in SQLite is the runtime
source of truth, which lets jobs and research artifacts reference an exact
definition hash rather than a mutable strategy name.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import yaml

from src.application.sqlite import migrate_sqlite, sqlite_connection
from src.indicators.custom import CUSTOM_IMPLEMENTATIONS
from src.indicators.registry import PandasTaAdapter
from src.platform_kernel import DomainValidationError

_STATUSES = {"DRAFT", "VALIDATED", "READY", "ACTIVE", "RETIRED"}
_SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
_OPERATIONS = {
    "add", "subtract", "multiply", "divide", "ratio", "logarithm", "shift",
    "rolling_mean", "rolling_std", "rolling_correlation", "clip", "scale",
    "piecewise_linear", "default", "conditional", "all", "any", "not",
    "greater_than", "greater_than_or_equal", "less_than", "less_than_or_equal",
    "equal", "percentile", "rank", "z_score", "sector_z_score", "weighted_sum",
    "modifier",
}


class StrategyDefinitions:
    def __init__(self, database: str | Path, indicators: PandasTaAdapter) -> None:
        self.database, self.indicators = Path(database), indicators
        migrate_sqlite(self.database, "strategy_definitions", {1: (
            """CREATE TABLE IF NOT EXISTS strategy_definitions (
                strategy_id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL,
                created_at TEXT NOT NULL)""",
            """CREATE TABLE IF NOT EXISTS strategy_revisions (
                revision_id TEXT PRIMARY KEY, strategy_id TEXT NOT NULL, schema_version INTEGER NOT NULL,
                semantic_version TEXT NOT NULL, source_yaml TEXT NOT NULL, canonical_json TEXT NOT NULL,
                definition_hash TEXT NOT NULL UNIQUE, status TEXT NOT NULL, created_at TEXT NOT NULL,
                validated_at TEXT, activated_at TEXT, retired_at TEXT,
                FOREIGN KEY(strategy_id) REFERENCES strategy_definitions(strategy_id))""",
            "CREATE INDEX IF NOT EXISTS strategy_revisions_by_strategy ON strategy_revisions(strategy_id, created_at DESC)",
        )})

    def create_from_yaml(self, source_yaml: object) -> dict[str, object]:
        if not isinstance(source_yaml, str) or not source_yaml.strip():
            raise DomainValidationError("strategy YAML is required")
        try:
            parsed = yaml.safe_load(source_yaml)
        except yaml.YAMLError as exc:
            raise DomainValidationError(f"strategy YAML is invalid: {exc}") from exc
        normalized = self._validate(parsed)
        canonical_json = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
        definition_hash = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
        strategy = normalized["strategy"]
        revision_id = str(uuid5(NAMESPACE_URL, f"strategy-revision:{definition_hash}"))
        now = datetime.now(UTC).isoformat()
        with sqlite_connection(self.database) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT OR IGNORE INTO strategy_definitions(strategy_id, name, description, created_at) VALUES (?, ?, ?, ?)",
                (strategy["id"], strategy["name"], strategy.get("description", ""), now),
            )
            connection.execute(
                """INSERT OR IGNORE INTO strategy_revisions
                (revision_id, strategy_id, schema_version, semantic_version, source_yaml, canonical_json,
                 definition_hash, status, created_at, validated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'VALIDATED', ?, ?)""",
                (revision_id, strategy["id"], normalized["schema_version"], strategy["version"],
                 source_yaml, canonical_json, definition_hash, now, now),
            )
        return self.get(revision_id)

    def get(self, revision_id: str) -> dict[str, object]:
        with sqlite_connection(self.database, read_only=True, row_factory=True) as connection:
            row = connection.execute("SELECT * FROM strategy_revisions WHERE revision_id=?", (revision_id,)).fetchone()
        if row is None:
            raise DomainValidationError("strategy revision was not found")
        return self._decode(row)

    def revisions(self, strategy_id: str) -> list[dict[str, object]]:
        with sqlite_connection(self.database, read_only=True, row_factory=True) as connection:
            rows = connection.execute("SELECT * FROM strategy_revisions WHERE strategy_id=? ORDER BY created_at DESC", (strategy_id,)).fetchall()
        return [self._decode(row) for row in rows]

    def active(self, strategy_id: str) -> dict[str, object] | None:
        with sqlite_connection(self.database, read_only=True, row_factory=True) as connection:
            row = connection.execute(
                "SELECT * FROM strategy_revisions WHERE strategy_id=? AND status='ACTIVE' ORDER BY activated_at DESC LIMIT 1",
                (strategy_id,),
            ).fetchone()
        return self._decode(row) if row is not None else None

    def active_revisions(self) -> list[dict[str, object]]:
        with sqlite_connection(self.database, read_only=True, row_factory=True) as connection:
            rows = connection.execute(
                "SELECT * FROM strategy_revisions WHERE status='ACTIVE' ORDER BY strategy_id"
            ).fetchall()
        return [self._decode(row) for row in rows]

    def activate(self, revision_id: str) -> dict[str, object]:
        now = datetime.now(UTC).isoformat()
        with sqlite_connection(self.database, row_factory=True) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT strategy_id, status FROM strategy_revisions WHERE revision_id=?", (revision_id,)).fetchone()
            if row is None:
                raise DomainValidationError("strategy revision was not found")
            if row["status"] not in {"VALIDATED", "READY", "ACTIVE"}:
                raise DomainValidationError("only a validated or ready strategy revision can be activated")
            connection.execute("UPDATE strategy_revisions SET status='RETIRED', retired_at=? WHERE strategy_id=? AND status='ACTIVE' AND revision_id<>?", (now, row["strategy_id"], revision_id))
            connection.execute("UPDATE strategy_revisions SET status='ACTIVE', activated_at=? WHERE revision_id=?", (now, revision_id))
        return self.get(revision_id)

    @staticmethod
    def _decode(row: Any) -> dict[str, object]:
        result = dict(row)
        result["definition"] = json.loads(result.pop("canonical_json"))
        return result

    def _validate(self, value: object) -> dict[str, Any]:
        if not isinstance(value, dict) or set(value) - {"schema_version", "strategy", "universe", "data_dependencies", "calculation", "indicators", "factors", "eligibility", "score", "ranking", "portfolio_policy"}:
            raise DomainValidationError("strategy definition contains unknown top-level fields")
        if value.get("schema_version") != 1:
            raise DomainValidationError("strategy schema_version must be 1")
        strategy = value.get("strategy")
        if not isinstance(strategy, dict) or set(strategy) - {"id", "name", "version", "description"} or not isinstance(strategy.get("id"), str) or not strategy["id"].replace("_", "").isalnum() or not isinstance(strategy.get("name"), str) or not isinstance(strategy.get("version"), str) or not _SEMVER.fullmatch(strategy["version"]):
            raise DomainValidationError("strategy id, name and version are required")
        calculation = value.get("calculation")
        if not isinstance(calculation, dict) or set(calculation) - {"instrument_implementation", "cross_section_implementation", "required_sessions"}:
            raise DomainValidationError("strategy calculation is required")
        implementation = calculation.get("instrument_implementation")
        cross_section = calculation.get("cross_section_implementation")
        if implementation not in CUSTOM_IMPLEMENTATIONS or (
            cross_section is not None and cross_section not in CUSTOM_IMPLEMENTATIONS
        ):
            raise DomainValidationError("strategy references an unavailable custom implementation")
        if isinstance(calculation.get("required_sessions"), bool) or not isinstance(calculation.get("required_sessions"), int) or calculation["required_sessions"] < 1:
            raise DomainValidationError("strategy required_sessions must be a positive integer")
        indicators = value.get("indicators", [])
        if not isinstance(indicators, list) or len({item.get("id") for item in indicators if isinstance(item, dict)}) != len(indicators):
            raise DomainValidationError("strategy indicators must have unique ids")
        indicator_ids: set[str] = set()
        for item in indicators:
            if not isinstance(item, dict) or set(item) - {"id", "provider", "function", "inputs", "parameters", "output"}:
                raise DomainValidationError("indicator node is invalid")
            if not isinstance(item.get("id"), str) or not isinstance(item.get("function"), str) or item.get("provider") != "pandas_ta" or not isinstance(item.get("inputs"), dict) or not isinstance(item.get("parameters", {}), dict):
                raise DomainValidationError("indicator nodes currently require an approved pandas_ta function")
            spec = self.indicators.spec(item["function"])
            if set(item["inputs"]) != set(spec.required_inputs):
                raise DomainValidationError(f"indicator '{item['id']}' inputs do not match '{spec.key}'")
            self.indicators._validate_parameters(spec, item.get("parameters", {}))
            indicator_ids.add(item["id"])
        for section in ("factors", "eligibility", "score"):
            if section in value:
                self._validate_operations(value[section], indicator_ids)
        factors = value.get("factors")
        if not isinstance(factors, dict) or not factors:
            raise DomainValidationError("strategy factors are required")
        try:
            weights = [float(weight) for weight in factors.values()]
        except (TypeError, ValueError) as exc:
            raise DomainValidationError("strategy factor weights must be numeric") from exc
        if any(weight < 0 for weight in weights) or abs(sum(weights) - 1) > 1e-9:
            raise DomainValidationError("strategy factor weights must sum to one")
        ranking = value.get("ranking")
        if not isinstance(ranking, dict) or ranking.get("frequency") not in {"daily", "weekly"} or ranking.get("session") not in {"last_trading_session", "each_trading_session"}:
            raise DomainValidationError("ranking frequency and session are invalid")
        policy = value.get("portfolio_policy")
        required_policy = {"initial_capital", "max_positions", "exit_threshold", "buffer_percent", "max_concentration_pct"}
        if not isinstance(policy, dict) or set(policy) != required_policy:
            raise DomainValidationError("portfolio_policy must contain the complete supported schema")
        if isinstance(policy["max_positions"], bool) or not isinstance(policy["max_positions"], int) or not 1 <= policy["max_positions"] <= 50:
            raise DomainValidationError("portfolio_policy max_positions must be between 1 and 50")
        try:
            numeric_policy = {key: float(value) for key, value in policy.items() if key != "max_positions"}
        except (TypeError, ValueError) as exc:
            raise DomainValidationError("portfolio_policy values must be numeric") from exc
        if numeric_policy["initial_capital"] <= 0 or not 0 < numeric_policy["max_concentration_pct"] <= 1 or numeric_policy["exit_threshold"] < 0 or numeric_policy["buffer_percent"] < 0:
            raise DomainValidationError("portfolio_policy values are outside supported ranges")
        return value

    def _validate_operations(self, value: object, indicator_ids: set[str]) -> None:
        if isinstance(value, list):
            for item in value:
                self._validate_operations(item, indicator_ids)
            return
        if not isinstance(value, dict):
            return
        operation = value.get("operation")
        if operation is not None:
            if operation not in _OPERATIONS:
                raise DomainValidationError(f"operation '{operation}' is not approved")
            # Any string inputs must refer to a declared node or known market field.
            for key in ("input", "left", "right", "factor"):
                reference = value.get(key)
                if isinstance(reference, str) and reference not in indicator_ids and reference not in {"close", "high", "low", "volume", "benchmark.close"}:
                    raise DomainValidationError(f"operation references unknown value '{reference}'")
        for nested in value.values():
            self._validate_operations(nested, indicator_ids)
