"""Immutable corporate-action facts and derived adjusted-bar readback."""

import hashlib
import json
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from src.application.market_repository import MarketRepository
from src.application.publication import ArtifactPublisher
from src.execution_gateway import Ledger
from src.platform_kernel import DomainValidationError


class CorporateActions:
    def __init__(self, database: str | Path, market: MarketRepository, publisher: ArtifactPublisher, ledger: Ledger | None = None):
        self.database, self.market, self.publisher, self.ledger = Path(database), market, publisher, ledger

    def record(self, payload: dict[str, object]) -> dict[str, object]:
        required = {"instrument_id", "effective_date", "action_type", "ratio", "amount"}
        if not isinstance(payload, dict) or not required.issubset(payload) or set(payload) - required - {"liquidation_policy"}:
            raise DomainValidationError("corporate action requires instrument, date, type, ratio and amount")
        if self.market.instrument_by_id(str(payload["instrument_id"])) is None:
            raise DomainValidationError("instrument was not found")
        try:
            effective = date.fromisoformat(str(payload["effective_date"]))
            ratio = Decimal(str(payload["ratio"]))
            amount = Decimal(str(payload["amount"]))
        except (ValueError, InvalidOperation) as exc:
            raise DomainValidationError("corporate action values are invalid") from exc
        action_type = payload["action_type"]
        if action_type not in {"SPLIT", "BONUS", "DIVIDEND", "DELISTING"} or not ratio.is_finite() or ratio <= 0 or not amount.is_finite() or amount < 0:
            raise DomainValidationError("corporate action values are invalid")
        policy = payload.get("liquidation_policy", "LIQUIDATE_AT_LAST_AVAILABLE_CLOSE")
        if action_type == "DELISTING" and policy not in {"LIQUIDATE_AT_LAST_AVAILABLE_CLOSE", "HOLD_MANUAL_REVIEW"}:
            raise DomainValidationError("delisting liquidation policy is invalid")
        if action_type != "DELISTING" and "liquidation_policy" in payload:
            raise DomainValidationError("liquidation policy is only valid for delistings")
        fact = {"instrument_id": str(payload["instrument_id"]), "effective_date": effective.isoformat(),
                "action_type": action_type, "ratio": str(ratio), "amount": str(amount)}
        if action_type == "DELISTING":
            fact["liquidation_policy"] = policy
        action_id = str(uuid5(NAMESPACE_URL, "corporate-action:" + json.dumps(fact, sort_keys=True)))
        if not self.publisher.catalog.has(action_id):
            self.publisher.publish_json("corporate-actions/facts", action_id, {"action_id": action_id, **fact})
            self._qualify_dependents(action_id, fact["instrument_id"])
        return {"action_id": action_id, **fact}

    def _qualify_dependents(self, action_id: str, instrument_id: str) -> None:
        dependent_categories = ("research/", "actions/", "runs/backtests")
        for summary in self.publisher.catalog.artifacts():
            category = str(summary["category"])
            if not category.startswith(dependent_categories):
                continue
            try:
                _, payload = self.publisher.store.read_json(category, str(summary["artifact_id"]))
            except DomainValidationError:
                continue
            if instrument_id not in json.dumps(payload, sort_keys=True, default=str):
                continue
            if summary["status"] == "VALID":
                self.publisher.catalog.set_status(
                    str(summary["artifact_id"]), "QUALIFIED", "corporate action requires recalculation"
                )
            self.publisher.catalog.record_invalidation(
                action_id, str(summary["artifact_id"]), "corporate action requires recalculation"
            )

    def adjusted_bars(self, instrument_id: str, start_date: date, end_date: date) -> dict[str, object]:
        if self.market.instrument_by_id(instrument_id) is None:
            raise DomainValidationError("instrument was not found")
        bars = self.market.bars(instrument_id, start_date, end_date, limit=1000)
        actions = []
        for manifest in self.publisher.store.manifests():
            if manifest.category != "corporate-actions/facts":
                continue
            _, payload = self.publisher.store.read_json(manifest.category, manifest.artifact_id)
            if payload.get("instrument_id") == instrument_id:
                actions.append(payload)
        actions.sort(key=lambda item: str(item["effective_date"]))
        delisting = next((item for item in actions if item["action_type"] == "DELISTING"), None)
        adjusted = []
        for bar in bars:
            factor = Decimal(1)
            for action in actions:
                if str(action["effective_date"]) > str(bar["as_of_date"]):
                    if action["action_type"] == "SPLIT":
                        factor /= Decimal(str(action["ratio"]))
                    elif action["action_type"] == "BONUS":
                        factor /= Decimal(1) + Decimal(str(action["ratio"]))
            adjusted.append({**bar, "open": str(Decimal(str(bar["open"])) * factor),
                             "high": str(Decimal(str(bar["high"])) * factor),
                             "low": str(Decimal(str(bar["low"])) * factor),
                             "close": str(Decimal(str(bar["close"])) * factor),
                             "adjustment_factor": str(factor)})
        revision = hashlib.sha256(json.dumps({"instrument_id": instrument_id, "actions": actions}, sort_keys=True).encode()).hexdigest()
        return {"instrument_id": instrument_id, "start_date": start_date.isoformat(), "end_date": end_date.isoformat(),
                "adjustment_revision": revision, "basis": "CORPORATE_ACTION_FACTS", "raw_bars": bars, "bars": adjusted,
                "delisting": delisting,
                "liquidation_required": bool(delisting and end_date >= date.fromisoformat(str(delisting["effective_date"]))),}

    def liquidation_plan(self, account_id: str, as_of_date: date) -> dict[str, object]:
        """Create a reviewable portfolio liquidation plan for delisted open lots."""
        if self.ledger is None:
            raise DomainValidationError("ledger is unavailable for liquidation planning")
        projection = self.ledger.projection_at(account_id, as_of_date)
        actions: dict[str, dict[str, object]] = {}
        for manifest in self.publisher.store.manifests():
            if manifest.category != "corporate-actions/facts":
                continue
            _, fact = self.publisher.store.read_json(manifest.category, manifest.artifact_id)
            if fact.get("action_type") == "DELISTING" and date.fromisoformat(str(fact["effective_date"])) <= as_of_date and fact.get("liquidation_policy") == "LIQUIDATE_AT_LAST_AVAILABLE_CLOSE":
                actions[str(fact["instrument_id"])] = fact
        entries: list[dict[str, object]] = []
        for lot in projection.open_lots:
            fact = actions.get(lot.instrument_id)
            if fact is None:
                continue
            bars = self.market.bars(lot.instrument_id, date.min, as_of_date, limit=1000)
            if not bars:
                continue
            close = str(bars[-1]["close"])
            entries.append({"instrument_id": lot.instrument_id, "units": lot.remaining_units.units, "price": close, "effective_date": fact["effective_date"], "source_action_id": fact["action_id"], "execution": "REVIEW_REQUIRED"})
        return {"account_id": account_id, "as_of_date": as_of_date.isoformat(), "entries": entries, "fills_created": 0, "requires_operator_review": bool(entries)}
