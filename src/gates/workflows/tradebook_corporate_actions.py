"""Source-backed actions used to bridge corporate-action gaps in tradebooks.

Exchange records drive tradebook lot matching, not market price history.
Quantity mismatches never imply a split.
"""

import json
from datetime import date, timedelta
from fractions import Fraction
from time import monotonic

from src.domains.portfolio_accounting.tradebook import canonical_symbol
from src.domains.reference_data import NseClient
from src.gates.workflows.corporate_actions import CorporateActions
from src.platform_kernel import DomainValidationError
from src.platform_kernel.sqlite import sqlite_connection

NSE_SOURCE = "https://www.nseindia.com/companies-listing/corporate-filings-actions"


class TradebookCorporateActions:
    """Read exchange events independently of their price-history processing state."""

    def __init__(self, database, market, service=None):
        self.database, self.market, self.service = str(database), market, service
        self._coverage = None

    def resolve(self, trades, through):
        start = min(t["date"] for t in trades)
        warnings = []
        if self.service is not None:
            coverage = self._coverage
            if (
                not coverage
                or coverage[0] > start
                or coverage[1] < through
                or monotonic() - coverage[2] > 3600
            ):
                try:
                    # NSE date windows are bounded to one year; reuse session cookies.
                    client = NseClient(timeout_seconds=5)
                    first, last = date.fromisoformat(start), date.fromisoformat(through)
                    while first <= last:
                        end = min(first + timedelta(days=364), last)
                        self.service.detect_job(
                            {"start_date": first.isoformat(), "as_of_date": end.isoformat()},
                            client=client,
                        )
                        first = end + timedelta(days=1)
                    self._coverage = (start, through, monotonic())
                except DomainValidationError:
                    warnings.append(
                        "NSE corporate-action refresh failed. Using cached exchange records; missing actions may need review."
                    )
        symbols = {t["symbol"] for t in trades}
        with sqlite_connection(self.database, read_only=True, row_factory=True) as connection:
            records = connection.execute(
                "SELECT * FROM corporate_action_events WHERE ex_date>=? AND ex_date<=? ORDER BY ex_date,event_id",
                (start, through),
            ).fetchall()
        actions = {}
        identities = self.market.tracked_instruments()
        for record in records:
            symbol = canonical_symbol(record["symbol"])
            kind, day = record["action_type"], record["ex_date"]
            if symbol not in symbols or kind == "DIVIDEND":
                continue
            relevant = sorted(
                (t for t in trades if t["symbol"] == symbol),
                key=lambda t: (t["timestamp"], t["row"]),
            )
            before = [t for t in relevant if t["date"] < day and t["isin"]]
            after = [t for t in relevant if t["date"] >= day and t["isin"]]
            current = {
                i["isin"]
                for i in identities
                if canonical_symbol(i["symbol"]) == symbol and i["exchange"] == "NSE"
            }
            old_isin = before[-1]["isin"] if before else record["isin"]
            new_isin = (
                after[0]["isin"]
                if after
                else (next(iter(current)) if len(current) == 1 else record["isin"] or old_isin)
            )
            action = {
                "symbol": symbol,
                "action_type": kind,
                "effective_date": day,
                "old_isin": old_isin,
                "new_isin": new_isin,
                "source_url": NSE_SOURCE,
                "event_id": record["event_id"],
            }
            # A verified exchange event bridges an observed ISIN transition. A
            # quantity mismatch alone is never evidence for an action.
            if kind == "BONUS":
                action["new_isin"] = old_isin
                action["date_note"] = (
                    "Bonus acquisition date uses the exchange ex-date; verify the actual allotment date before tax reporting."
                )
            try:
                raw_numerator, raw_denominator = (
                    record["ratio_numerator"],
                    record["ratio_denominator"],
                )
                if raw_numerator is None or raw_denominator is None:
                    source = json.loads(record["raw_source_json"] or "{}")
                    ratio = (
                        CorporateActions.parse_ratio(
                            CorporateActions.source_ratio(str(source.get("subject", "")), kind),
                            kind,
                        )
                        if isinstance(source, dict)
                        else None
                    )
                    if ratio:
                        raw_numerator, raw_denominator = ratio
                numerator = Fraction(str(raw_numerator))
                denominator = Fraction(str(raw_denominator))
                if numerator <= 0 or denominator <= 0:
                    raise ValueError
                # Stored split ratios describe price adjustment (new FV / old
                # FV), whereas tradebook ratios describe share entitlement.
                factor = (
                    denominator / numerator
                    if kind == "SPLIT"
                    else (numerator + denominator) / denominator
                )
                action.update(numerator=factor.numerator, denominator=factor.denominator)
            except (ValueError, ZeroDivisionError):
                action["reason"] = (
                    f"{symbol}: exchange {kind.lower()} record has no usable ratio; manual corporate-action review required"
                )
            if kind not in {"SPLIT", "BONUS"}:
                action["reason"] = (
                    f"{symbol}: {kind.lower()} requires sourced entitlement and cost allocation; manual corporate-action review required"
                )
            key = (symbol, day, kind)
            prior = actions.get(key)
            if prior and (prior.get("numerator"), prior.get("denominator")) != (
                action.get("numerator"),
                action.get("denominator"),
            ):
                action["reason"] = (
                    f"{symbol}: conflicting exchange corporate-action ratios require review"
                )
            actions[key] = action
        return sorted(actions.values(), key=lambda a: a["effective_date"]), warnings
