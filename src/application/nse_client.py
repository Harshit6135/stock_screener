"""Small, validated boundary for NSE constituent and corporate action downloads."""

from __future__ import annotations

import csv
import io
import json

import requests

from src.platform_kernel import DomainValidationError

NIFTY_500_URL = "https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv"
NSE_CA_URL = "https://www.nseindia.com/api/corporate-actions"
NSE_BASE_URL = "https://www.nseindia.com"


class NseClient:
    def __init__(self, *, session: requests.Session | None = None, timeout_seconds: float = 20.0) -> None:
        self.session = session or requests.Session()
        self.timeout_seconds = timeout_seconds
        self._nse_cookies_set = False

    def _ensure_nse_cookies(self) -> None:
        """Phase 3: Establish NSE session cookies before API calls."""
        if self._nse_cookies_set:
            return
        try:
            self.session.get(NSE_BASE_URL, timeout=self.timeout_seconds)
            self._nse_cookies_set = True
        except requests.RequestException:
            pass  # Continue without cookies; the API call will fail naturally

    def nifty_500_csv(self) -> tuple[str, bytes]:
        try:
            response = self.session.get(NIFTY_500_URL, timeout=self.timeout_seconds)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise DomainValidationError("NSE constituent download failed") from exc
        raw = response.content
        if not raw or len(raw) > 25_000_000:
            raise DomainValidationError("NSE constituent response is invalid")
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise DomainValidationError("NSE constituent CSV encoding is invalid") from exc
        if "<html" in text.lower() or "access denied" in text.lower():
            raise DomainValidationError("NSE constituent response is not a CSV")
        reader = csv.DictReader(io.StringIO(text))
        required = {"Company Name", "Industry", "Symbol", "Series", "ISIN Code"}
        if reader.fieldnames is None or not required.issubset({field.strip() for field in reader.fieldnames}):
            raise DomainValidationError("NSE constituent CSV columns are invalid")
        return NIFTY_500_URL, raw

    def corporate_actions(self, *, from_date: str | None = None, to_date: str | None = None,
                          segment: str = "equities") -> list[dict[str, str]]:
        """Phase 3 Task 3.2: Fetch corporate actions from NSE API.

        Returns a list of raw records with keys like: symbol, subject, exDate, etc.
        """
        self._ensure_nse_cookies()
        params: dict[str, str] = {"index": segment}
        if from_date:
            params["from_date"] = from_date
        if to_date:
            params["to_date"] = to_date
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
            "Referer": NSE_BASE_URL,
        }
        try:
            response = self.session.get(
                NSE_CA_URL, params=params, headers=headers, timeout=self.timeout_seconds,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise DomainValidationError("NSE corporate action download failed") from exc
        try:
            data = response.json()
        except (ValueError, json.JSONDecodeError) as exc:
            raise DomainValidationError("NSE corporate action response is not valid JSON") from exc
        if not isinstance(data, list):
            raise DomainValidationError("NSE corporate action response format is unexpected")
        return data


