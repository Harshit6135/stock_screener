from src.domains.execution import BrokerOrderRepository
from src.platform_kernel.sqlite import sqlite_connection


def test_broker_order_repository_preserves_schema_versions_and_state(tmp_path):
    database = tmp_path / "broker.db"
    repository = BrokerOrderRepository(database)
    with sqlite_connection(database, read_only=True, row_factory=True) as connection:
        versions = connection.execute(
            "SELECT version FROM system_schema_migrations WHERE namespace='broker_orders' "
            "ORDER BY version"
        ).fetchall()
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert [row["version"] for row in versions] == [1]
    assert {
        "broker_orders",
        "broker_execution_events",
        "broker_baskets",
        "broker_basket_orders",
    } <= tables

    payload = {
        "account_id": "paper",
        "proposal_id": "proposal-1",
        "idempotency_key": "order-1",
        "instrument_id": "instrument-1",
        "symbol": "ABC",
        "exchange": "NSE",
        "side": "BUY",
        "quantity": 2,
        "order_type": "MARKET",
    }
    order = repository.create_intent(
        order_id="order-id-1",
        payload=payload,
        variety="regular",
        created_at="2026-10-03T00:00:00+00:00",
    )
    replay = repository.create_intent(
        order_id="order-id-2",
        payload=payload,
        variety="regular",
        created_at="2026-10-03T00:00:01+00:00",
    )
    assert order["order_id"] == replay["order_id"] == "order-id-1"
    repository.claim_submission("order-id-1", "2026-10-03T00:00:02+00:00")
    repository.mark_submit_unknown("order-id-1", "TimeoutError", "2026-10-03T00:00:03+00:00")
    assert repository.get("order-id-1")["status"] == "SUBMIT_UNKNOWN"
    with sqlite_connection(database, read_only=True) as connection:
        event_types = [
            row[0]
            for row in connection.execute(
                "SELECT event_type FROM broker_execution_events "
                "WHERE order_id='order-id-1' ORDER BY event_id"
            ).fetchall()
        ]
    assert event_types == ["LOCAL_CREATED", "SUBMITTING", "SUBMIT_UNKNOWN"]
