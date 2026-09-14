"""Recording policy coordinates validated caller context with persisted delivery references."""

import json

import pytest
from sqlalchemy import select

from kyno.delivery_recording import DeliveryRecorder
from kyno.store.delivery_record import SqlDeliveryRecordStore
from kyno.store.sql import SqlConstitutionStore


@pytest.fixture
def store():
    store = SqlConstitutionStore(url="sqlite://")
    store.create_all()
    return store


@pytest.mark.parametrize("policy, status", [("never", "disabled"), ("always", "recorded")])
def test_given_recording_policy_when_recording_then_only_always_persists_a_record(
    store, policy, status
):
    direction = {"version": 0, "mission": "Original"}
    result = DeliveryRecorder(SqlDeliveryRecordStore(store.engine), policy).record(
        direction,
        operation="get_mission",
        constitution="missing",
        arguments={
            "correlation_id": "session",
            "metadata": {"nested": [1]},
            "known_version": object(),
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
        assert record["known_version"] is None
        assert record["detail_level"] is None
        assert json.loads(record["selection"]) == {}


def test_given_missing_delivery_table_when_recording_then_database_failure_returns_failed(store):
    store.metadata.tables["kyno_delivery_records"].drop(store.engine)
    result = DeliveryRecorder(SqlDeliveryRecordStore(store.engine), "always").record(
        {"version": 0}, operation="get_constitution", constitution="missing", arguments={}
    )
    assert result == {"status": "failed", "record_id": None}
