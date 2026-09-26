"""Recording database waits use their own limits without changing ordinary connections."""

import sqlite3

import pytest
from sqlalchemy import create_engine, delete

from kyno.delivery_recording import DeliveryRecorder
from kyno.service import ControlPlane
from kyno.store.delivery_record import SqlDeliveryRecordStore
from kyno.store.recording_connection import recording_transaction


@pytest.fixture
def delivery_table(store):
    return next(
        table for table in store.metadata.tables.values() if table.name.endswith("delivery_records")
    )


@pytest.fixture
def records(store, delivery_table):
    return SqlDeliveryRecordStore(
        store.engine,
        prefix=delivery_table.name.removesuffix("delivery_records"),
        recording_url=store.engine.url,
    )


@pytest.mark.parametrize("in_memory", [False, True])
@pytest.mark.parametrize("fail", [False, True])
def test_given_sqlite_connection_when_recording_finishes_then_original_busy_timeout_is_preserved(
    tmp_path, in_memory, fail
):
    engine = create_engine("sqlite://" if in_memory else f"sqlite:///{tmp_path / 'recording.db'}")
    try:
        with engine.connect() as connection:
            original = connection.exec_driver_sql("PRAGMA busy_timeout").scalar_one()
        try:
            with recording_transaction(engine, 0.025, database_url=engine.url) as connection:
                assert connection.exec_driver_sql("PRAGMA busy_timeout").scalar_one() == 25
                if fail:
                    raise ValueError("rollback")
        except ValueError:
            assert fail
        with engine.connect() as connection:
            assert connection.exec_driver_sql("PRAGMA busy_timeout").scalar_one() == original
    finally:
        engine.dispose()


def test_given_pool_has_no_free_connections_when_recording_then_query_uses_a_separate_connection(
    tmp_path,
):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'recording.db'}", pool_size=1, max_overflow=0, pool_timeout=0
    )
    try:
        with (
            engine.connect(),
            recording_transaction(engine, 0.025, database_url=engine.url) as connection,
        ):
            assert connection.exec_driver_sql("SELECT 1").scalar_one() == 1
    finally:
        engine.dispose()


def test_given_database_when_recording_then_timeout_changes_only_for_recording_connection(store):
    statements = {
        "sqlite": ("PRAGMA busy_timeout", 25),
        "postgresql": ("SHOW statement_timeout", "25ms"),
        "mysql": ("SELECT @@session.innodb_lock_wait_timeout", 1),
    }
    statement, expected = statements[store.engine.dialect.name]
    with store.engine.connect() as connection:
        original = connection.exec_driver_sql(statement).scalar_one()
    with recording_transaction(store.engine, 0.025, database_url=store.engine.url) as connection:
        assert connection.exec_driver_sql(statement).scalar_one() == expected
    with store.engine.connect() as connection:
        assert connection.exec_driver_sql(statement).scalar_one() == original


def test_given_locked_postgres_table_when_recording_then_it_fails_and_recovers_after_unlock(
    store, delivery_table
):
    if store.engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL table-lock behavior")
    engine = create_engine(
        store.engine.url.update_query_dict({"options": "-c statement_timeout=5000"})
    )
    records = SqlDeliveryRecordStore(
        engine,
        prefix=delivery_table.name.removesuffix("delivery_records"),
        recording_url=engine.url,
    )
    recorder = DeliveryRecorder(records, "always", timeout_seconds=0.025)
    try:
        with store.engine.begin() as lock:
            lock.exec_driver_sql(f'LOCK TABLE "{delivery_table.name}" IN ACCESS EXCLUSIVE MODE')
            result = recorder.record(
                {"version": 0}, operation="get_mission", constitution="missing", arguments={}
            )
            assert result == {"status": "failed", "record_id": None}
        assert records.list()["items"] == []
        result = recorder.record(
            {"version": 0}, operation="get_mission", constitution="missing", arguments={}
        )
        assert result["status"] == "recorded"
        assert records.get(result["record_id"])["served_version"] == 0
    finally:
        engine.dispose()


def test_given_version_when_delivery_recorder_record_uses_timeout_then_reference_and_delta_persist(
    store, records
):
    plane = ControlPlane(store)
    plane.apply_direction(constitution_key="team", mission="Help customers", change_note="initial")
    result = DeliveryRecorder(records, "always", timeout_seconds=1).record(
        {"version": 1, "delta": ["Mission changed."]},
        operation="get_constitution",
        constitution="team",
        arguments={},
    )
    assert result["status"] == "recorded"
    record = records.get(result["record_id"])
    assert record["served_version"] == 1
    assert record["constitution_id"] is not None
    assert record["delta"] == ["Mission changed."]


def test_given_recording_transaction_failure_when_rolling_back_then_existing_records_remain(
    store, records, delivery_table
):
    result = DeliveryRecorder(records, "always").record(
        {"version": 0}, operation="get_mission", constitution="missing", arguments={}
    )
    with (
        pytest.raises(ValueError, match="abort"),
        recording_transaction(store.engine, 1, database_url=store.engine.url) as connection,
    ):
        connection.execute(delete(delivery_table))
        raise ValueError("abort")
    assert records.get(result["record_id"])["served_version"] == 0


def test_given_injected_connection_creator_when_recording_without_a_url_then_it_is_rejected(
    tmp_path,
):
    actual_database = tmp_path / "actual.db"
    url_database = tmp_path / "url.db"
    engine = create_engine(
        f"sqlite:///{url_database}", creator=lambda: sqlite3.connect(actual_database)
    )
    try:
        with engine.connect() as connection:
            assert connection.exec_driver_sql("SELECT 1").scalar_one() == 1
        with (
            pytest.raises(ValueError, match="explicit recording database URL"),
            recording_transaction(engine, 1),
        ):
            pass
        assert not url_database.exists()
    finally:
        engine.dispose()


def test_given_different_recording_url_when_opening_transaction_then_it_is_rejected(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'direction.db'}")
    try:
        with (
            pytest.raises(ValueError, match="must match the direction engine URL"),
            recording_transaction(engine, 1, database_url=f"sqlite:///{tmp_path / 'other.db'}"),
        ):
            pass
        assert not (tmp_path / "other.db").exists()
    finally:
        engine.dispose()


def test_given_locked_mysql_table_when_recording_then_it_fails_and_recovers_after_unlock(
    store, delivery_table
):
    if store.engine.dialect.name != "mysql":
        pytest.skip("MySQL table-lock behavior")
    engine = create_engine(
        store.engine.url.update_query_dict({"read_timeout": "5", "write_timeout": "5"})
    )
    records = SqlDeliveryRecordStore(
        engine,
        prefix=delivery_table.name.removesuffix("delivery_records"),
        recording_url=engine.url,
    )
    recorder = DeliveryRecorder(records, "always", timeout_seconds=1)
    try:
        with store.engine.connect() as lock:
            lock.exec_driver_sql(f"LOCK TABLES `{delivery_table.name}` WRITE")
            try:
                result = recorder.record(
                    {"version": 0}, operation="get_mission", constitution="missing", arguments={}
                )
                assert result == {"status": "failed", "record_id": None}
            finally:
                lock.exec_driver_sql("UNLOCK TABLES")
        assert records.list()["items"] == []
        result = recorder.record(
            {"version": 0}, operation="get_mission", constitution="missing", arguments={}
        )
        assert result["status"] == "recorded"
        assert records.get(result["record_id"])["served_version"] == 0
    finally:
        engine.dispose()
