"""Read-only live smoke test for Kite plus the v4 liquidity-universe path.

Requires ignored local files ``local_secrets.py`` (``KITE_API_KEY``) and
``access_token.txt``. It never submits an order or writes to ``instance/``.
"""

import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from kiteconnect import KiteConnect  # type: ignore[import-untyped]

from src.application.providers import KiteHistoricalBarsProvider

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _kite_client() -> KiteConnect:
    try:
        from local_secrets import KITE_API_KEY
    except ImportError as exc:
        raise RuntimeError("local_secrets.py with KITE_API_KEY is required") from exc
    token_path = PROJECT_ROOT / "access_token.txt"
    if not token_path.is_file() or not token_path.read_text(encoding="utf-8").strip():
        raise RuntimeError("access_token.txt is required")
    client = KiteConnect(api_key=KITE_API_KEY)
    client.set_access_token(token_path.read_text(encoding="utf-8").strip())
    return client


def _find_instrument(records: list[dict[str, object]], symbol: str) -> dict[str, object]:
    matches = [
        record
        for record in records
        if record.get("tradingsymbol") == symbol
        and record.get("exchange") == "NSE"
        and record.get("instrument_type") == "EQ"
    ]
    if len(matches) != 1:
        raise RuntimeError(f"expected one NSE equity instrument for {symbol}")
    return matches[0]


def _find_index(records: list[dict[str, object]]) -> dict[str, object]:
    matches = [record for record in records if record.get("tradingsymbol") == "NIFTY 500"]
    if len(matches) != 1:
        raise RuntimeError("expected one NIFTY 500 instrument in Kite's NSE master")
    return matches[0]


def main() -> int:
    try:
        client = _kite_client()
        client.profile()  # Authentication validation; profile content is intentionally not logged.
        nse_instruments = list(client.instruments("NSE"))
        reliance = _find_instrument(nse_instruments, "RELIANCE")
        nifty_500 = _find_index(nse_instruments)
        quote = client.quote(["NSE:RELIANCE"])
        if "NSE:RELIANCE" not in quote:
            raise RuntimeError("Kite quote response omitted NSE:RELIANCE")

        end_date = datetime.now(UTC).date()
        start_date = end_date - timedelta(days=110)
        provider = KiteHistoricalBarsProvider(client)
        reliance_bars = provider.get_bars(str(reliance["instrument_token"]), start_date, end_date)
        nifty_bars = provider.get_bars(str(nifty_500["instrument_token"]), start_date, end_date)
        if len(reliance_bars) < 54 or not nifty_bars:
            raise RuntimeError("Kite returned insufficient equity or Nifty 500 daily history")

        with TemporaryDirectory(prefix="screener-kite-smoke-") as temporary_directory:
            temporary_path = Path(temporary_directory)
            os.environ["SCREENER_DATA_DIRECTORY"] = str(temporary_path)
            from run import create_app

            class IntegrationConfig:
                TESTING = True
                SECRET_KEY = "integration-only"
                DATA_DIRECTORY = temporary_path

            app = create_app(IntegrationConfig)
            services = app.extensions["screener_services"]
            instrument_id = str(uuid4())
            latest_date = reliance_bars[-1].as_of_date
            command = {
                "as_of_date": latest_date.isoformat(),
                "policy": {
                    "policy_id": str(uuid4()),
                    "name": "Kite smoke liquidity policy",
                    "lookback_sessions": 60,
                    "minimum_valid_sessions": 54,
                    "minimum_median_daily_turnover": 0,
                },
                "instruments": [
                    {
                        "instrument_id": instrument_id,
                        "isin": str(reliance.get("isin") or "UNKNOWN"),
                        "symbol": "RELIANCE",
                        "exchange": "NSE",
                    }
                ],
                "bars": [
                    {
                        "instrument_id": instrument_id,
                        "as_of_date": bar.as_of_date.isoformat(),
                        "open": str(bar.open),
                        "high": str(bar.high),
                        "low": str(bar.low),
                        "close": str(bar.close),
                        "volume": bar.volume,
                    }
                    for bar in reliance_bars
                ],
            }
            services.jobs.submit(
                f"kite-smoke:{latest_date.isoformat()}:{reliance['instrument_token']}",
                "research.build-liquidity-universe",
                command,
                max_attempts=1,
            )
            completed = services.worker.run_once()
            if completed is None or completed.result is None:
                raise RuntimeError("liquidity universe worker did not complete")
            response = app.test_client().get(
                f"/api/v2/reference/liquidity-universes/{completed.result['artifact_id']}"
            )
            if response.status_code != 200:
                raise RuntimeError("published liquidity universe was not readable through the API")
            member = response.json["universe"]["members"][0]

        print(
            "Kite integration smoke passed: "
            f"NSE instruments={len(nse_instruments)}, RELIANCE bars={len(reliance_bars)}, "
            f"Nifty 500 bars={len(nifty_bars)}, as_of={latest_date}, "
            f"eligible={member['eligible']}, exclusions={len(member['exclusion_reasons'])}."
        )
        return 0
    except Exception as exc:  # noqa: BLE001 - integration boundary must not print credentials
        print(f"Kite integration smoke failed: {type(exc).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
