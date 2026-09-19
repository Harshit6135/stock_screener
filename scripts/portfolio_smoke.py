"""Exercise the real portfolio HTTP routes against an isolated account."""

from datetime import date
from tempfile import TemporaryDirectory
from uuid import uuid4

from run import create_app
from src.application.market_repository import TrackedInstrument
from src.application.runtime import RuntimeConfig


def main() -> int:
    with TemporaryDirectory() as root:

        class SmokeConfig(RuntimeConfig):
            DATA_DIRECTORY = root

        app = create_app(SmokeConfig)
        services = app.extensions["screener_services"]
        services.market.upsert_instruments(
            [TrackedInstrument(str(uuid4()), "INE000000001", "ABC", "NSE", "42", date(2026, 9, 1))]
        )
        client = app.test_client()
        opened = client.post(
            "/api/v2/portfolio/accounts",
            json={"account_id": "portfolio", "opening_cash": "1000"},
        )
        if opened.status_code != 201:
            raise RuntimeError("portfolio account creation failed")
        buy = client.post(
            "/api/v2/portfolio/accounts/portfolio/fills",
            json={
                "idempotency_key": "buy-1",
                "expected_version": 0,
                "fills": [
                    {
                        "symbol": "ABC",
                        "fill_date": "2026-09-02",
                        "side": "BUY",
                        "units": 2,
                        "price": "100",
                    }
                ],
            },
        )
        if buy.status_code != 201:
            raise RuntimeError("portfolio buy fill failed")
        sell = client.post(
            "/api/v2/portfolio/accounts/portfolio/fills",
            json={
                "idempotency_key": "sell-1",
                "expected_version": 1,
                "fills": [
                    {
                        "symbol": "ABC",
                        "fill_date": "2026-09-03",
                        "side": "SELL",
                        "units": 1,
                        "price": "110",
                    }
                ],
            },
        )
        if sell.status_code != 201:
            raise RuntimeError("portfolio sell fill failed")
        account = client.get("/api/v2/portfolio/accounts/portfolio")
        events = client.get("/api/v2/portfolio/accounts/portfolio/events")
        if (
            account.status_code != 200
            or account.json["cash"] != "910"
            or account.json["realised_pnl"] != "10"
            or account.json["open_lots"][0]["units"] != 1
            or len(events.json["events"]) != 2
        ):
            raise RuntimeError("portfolio projection or event readback failed")
        print("portfolio_verified=account,buy,sell,FIFO,events", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
