"""Recording policy coordinates validated caller context with persisted delivery references."""

import json

import pytest
from sqlalchemy import select

from kyno.delivery_recording import DeliveryRecorder
from kyno.store.delivery_record import SqlDeliveryRecordStore
from kyno.store.sql import SqlConstitutionStore


@pytest.fixture
def store(memory_store):
    return memory_store


@pytest.mark.parametrize("policy, status", [("never", "disabled"), ("always", "recorded")])
@pytest.mark.parametrize("known_version", [None, 0, 3])
def test_given_recording_policy_when_recording_then_only_always_persists_a_record(
    store, policy, status, known_version
):
    direction = {"version": 0, "mission": "Original"}
    result = DeliveryRecorder(SqlDeliveryRecordStore(store.engine), policy).record(
        direction,
        operation="get_mission",
        constitution="missing",
        arguments={
            "correlation_id": "session",
            "metadata": {"nested": [1]},
            **({"known_version": known_version} if known_version is not None else {}),
            "detail": object(),
            "title": object(),
        },
        requester={"id": 3},
    )
    direction["mission"] = "Changed"
    assert result["status"] == status
    with store.engine.connect() as connection:
        records = (
            connection.execute(select(store.metadata.tables["kyno_delivery_records"]))
            .mappings()
            .all()
        )
    if policy == "never":
        assert records == []
    else:
        assert len(records) == 1
        record = records[0]
        assert record["record_id"] == result["record_id"]
        assert record["served_version"] == 0
        assert json.loads(record["delta"]) is None
        assert "direction" not in record
        assert json.loads(record["requester"]) == {"id": 3}
        assert json.loads(record["metadata"]) == {"nested": [1]}
        assert record["correlation_id"] == "session"
        assert record["known_version"] == known_version
        assert record["detail_level"] is None
        assert json.loads(record["selection"]) == {}


def test_given_missing_delivery_table_when_recording_then_database_failure_returns_failed(store):
    store.metadata.tables["kyno_delivery_records"].drop(store.engine)
    result = DeliveryRecorder(SqlDeliveryRecordStore(store.engine), "always").record(
        {"version": 0}, operation="get_constitution", constitution="missing", arguments={}
    )
    assert result == {"status": "failed", "record_id": None}


def test_given_locked_sqlite_when_recording_then_it_fails_without_a_record_and_recovers_on_unlock(
    tmp_path,
):
    store = SqlConstitutionStore(url=f"sqlite:///{tmp_path / 'recording.db'}")
    store.create_all()
    records = SqlDeliveryRecordStore(store.engine, recording_url=store.engine.url)
    recorder = DeliveryRecorder(records, "always", timeout_seconds=0.01)
    direction = {"version": 0, "mission": "Available direction"}
    try:
        with store.engine.connect() as lock:
            lock.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                result = recorder.record(
                    direction, operation="get_mission", constitution="missing", arguments={}
                )
                assert result == {"status": "failed", "record_id": None}
                assert records.list()["items"] == []
                assert direction == {"version": 0, "mission": "Available direction"}
            finally:
                lock.rollback()
        result = recorder.record(
            direction, operation="get_mission", constitution="missing", arguments={}
        )
        assert result["status"] == "recorded"
        assert [record["record_id"] for record in records.list()["items"]] == [result["record_id"]]
    finally:
        store.engine.dispose()
