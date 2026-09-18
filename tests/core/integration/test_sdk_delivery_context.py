"""SDK binders send application context to Core's delivery history."""

import pytest

from kyno.delivery import RecordingPolicy
from kyno.delivery_recording import DeliveryRecorder
from kyno.store.delivery_record import SqlDeliveryRecordStore


@pytest.mark.parametrize("constitution", ["default", "support"])
def test_given_distinct_binders_when_bind_runs_then_records_keep_each_constitution_and_context(
    mcp_connection, memory_store, constitution
):
    connection, control_plane = mcp_connection
    history = SqlDeliveryRecordStore(memory_store.engine)
    control_plane.delivery_recorder = DeliveryRecorder(history, RecordingPolicy.ALWAYS)
    control_plane.apply_direction(mission="Support customers", change_note="initial")
    if constitution != "default":
        control_plane.apply_direction(
            mission="Support customers", change_note="initial", constitution_key=constitution
        )
    metadata = {"experiment": {"variant": "A"}}
    first = connection.binder(constitution, correlation_id="workflow-one", metadata=metadata)
    second = connection.binder(correlation_id="workflow-two", metadata={"variant": "B"})
    metadata["experiment"]["variant"] = "changed"

    assert first.bind().mission == "Support customers"
    assert second.bind().mission == "Support customers"
    assert connection.binder().bind().mission == "Support customers"
    assert first.bind().mission == "Support customers"
    records = history.list()["items"]
    assert [record["requested_constitution"] for record in records] == [
        constitution,
        "default",
        "default",
        constitution,
    ]
    assert [record["last_seen_version"] for record in records] == [0, 0, 0, 1]
    assert [record["correlation_id"] for record in records] == [
        "workflow-one",
        "workflow-two",
        None,
        "workflow-one",
    ]
    assert [record["metadata"] for record in records] == [
        {"experiment": {"variant": "A"}},
        {"variant": "B"},
        {},
        {"experiment": {"variant": "A"}},
    ]


@pytest.mark.parametrize(
    "context",
    [
        {"correlation_id": 1},
        {"correlation_id": "x" * 256},
        {"metadata": {"value": float("nan")}},
        {"metadata": {"value": "x" * 16_384}},
        {"metadata": []},
    ],
)
def test_given_invalid_delivery_context_when_building_a_binder_then_it_is_rejected(
    mcp_connection, context
):
    connection, _control_plane = mcp_connection
    with pytest.raises(ValueError):
        connection.binder(**context)
