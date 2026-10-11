from src.domains.portfolio_engine import RiskReservationRepository
from src.platform_kernel.sqlite import sqlite_connection


def test_risk_reservations_share_the_callers_transaction(tmp_path):
    database = tmp_path / "system.db"
    repository = RiskReservationRepository(database)

    with sqlite_connection(database, row_factory=True) as connection:
        connection.execute("BEGIN IMMEDIATE")
        repository.upsert(
            connection,
            "reservation-1",
            "account-1",
            "proposal-1",
            '[{"side":"BUY"}]',
            4,
            7,
        )
        row = repository.active_for_account(connection, "account-1")[0]
        assert row["orders_json"] == '[{"side":"BUY"}]'
        assert row["ledger_version"] == 4
        repository.upsert(
            connection,
            "reservation-1",
            "account-1",
            "proposal-1",
            '[{"side":"BUY","units":2}]',
            5,
            8,
        )
        repository.release(connection, "reservation-1")
        assert repository.active_for_account(connection, "account-1") == []

    with sqlite_connection(database, read_only=True, row_factory=True) as connection:
        reservation = connection.execute(
            "SELECT * FROM risk_reservations WHERE reservation_id='reservation-1'"
        ).fetchone()
        versions = connection.execute(
            "SELECT version FROM system_schema_migrations "
            "WHERE namespace='risk_reservations' ORDER BY version"
        ).fetchall()
    assert reservation["status"] == "RELEASED"
    assert reservation["ledger_version"] == 5
    assert [row[0] for row in versions] == [1]


def test_risk_reservation_changes_rollback_with_the_callers_unit_of_work(tmp_path):
    database = tmp_path / "system.db"
    repository = RiskReservationRepository(database)

    with sqlite_connection(database) as connection:
        connection.execute("BEGIN IMMEDIATE")
        repository.upsert(
            connection,
            "rolled-back",
            "account-1",
            "proposal-1",
            "[]",
            0,
            0,
        )
        connection.rollback()

    with sqlite_connection(database, read_only=True, row_factory=True) as connection:
        row = connection.execute(
            "SELECT 1 FROM risk_reservations WHERE reservation_id='rolled-back'"
        ).fetchone()
    assert row is None
