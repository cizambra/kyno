"""SDK constitution reads select current or historical agent-context projections over MCP."""

from dataclasses import replace

import pytest

from kyno.delivery_recording import DeliveryRecorder
from kyno.sdk.errors import KynoHistoryError
from kyno.store.delivery_record import SqlDeliveryRecordStore
from kyno.wire.models import DetailLevel


@pytest.fixture
def constitution_connection(mcp_connection):
    connection, control_plane = mcp_connection
    control_plane.set_direction(
        mission="Original mission",
        declaration="Original declaration",
        principles=[{"title": "Honesty", "description": "State the facts."}],
        change_note="Initial version",
        constitution="example",
    )
    return connection, control_plane


@pytest.mark.parametrize("context", ["compact", DetailLevel.COMPACT, "full", DetailLevel.FULL])
@pytest.mark.parametrize("version", [None, 1])
def test_given_agent_direction_when_reading_constitution_then_requested_context_matches(
    constitution_connection, context, version
):
    connection, control_plane = constitution_connection
    original = connection.binder(context=context).bind("example")
    if version is not None:
        control_plane.set_direction(
            mission="New mission", change_note="Updated", constitution="example"
        )
    binder = connection.binder(context=context)
    current = binder.bind("example")

    direction = connection.get_constitution("example", version=version, context=context)

    assert direction == replace(original, change_notes=(), delta=())
    assert direction.context is DetailLevel(context)
    assert direction.version == 1
    assert direction.mission == "Original mission"
    full = context == DetailLevel.FULL
    assert direction.declaration == ("Original declaration" if full else "")
    assert direction.principles[0].description == ("State the facts." if full else "")
    assert ("Original declaration" in direction.render()) is full
    assert ("State the facts." in direction.render()) is full
    assert binder.cell.get("example") is current


def test_given_newer_direction_when_version_is_omitted_then_current_compact_direction_returns(
    constitution_connection,
):
    connection, control_plane = constitution_connection
    control_plane.set_direction(
        mission="Current mission", change_note="Updated", constitution="example"
    )
    direction = connection.get_constitution("example")
    assert direction.version == 2
    assert direction.mission == "Current mission"
    assert direction.context is DetailLevel.COMPACT
    assert direction.declaration == direction.principles[0].description == ""


@pytest.mark.parametrize("constitution, version", [("example", 2), ("unknown", 1)])
def test_given_missing_exact_version_when_reading_then_version_not_found_is_raised(
    constitution_connection, constitution, version
):
    connection, _ = constitution_connection
    with pytest.raises(KynoHistoryError, match="version.*not found"):
        connection.get_constitution(constitution, version=version)


@pytest.mark.parametrize("context", list(DetailLevel))
def test_given_live_direction_when_reading_version_zero_then_empty_selected_context_returns(
    constitution_connection, context
):
    connection, _ = constitution_connection
    direction = connection.get_constitution("example", version=0, context=context)
    assert direction.version == 0
    assert direction.mission == direction.declaration == ""
    assert direction.principles == ()
    assert direction.context is context


@pytest.mark.parametrize("version, served_version", [(None, 2), (1, 1), (0, 0)])
def test_given_recording_enabled_when_sdk_reads_constitution_then_selected_version_is_recorded(
    constitution_connection, memory_store, version, served_version
):
    connection, control_plane = constitution_connection
    history = SqlDeliveryRecordStore(memory_store.engine)
    control_plane.delivery_recorder = DeliveryRecorder(history, "always")
    control_plane.set_direction(
        mission="Current mission", change_note="Updated", constitution="example"
    )

    direction = connection.get_constitution("example", version=version)

    record = history.list()["items"][0]
    assert record["served_version"] == direction.version == served_version
    assert record["known_version"] is None
    assert record["operation"] == "get_constitution"
    assert record["detail_level"] == "compact"


def test_given_recording_enabled_when_exact_version_is_missing_then_no_delivery_is_recorded(
    constitution_connection,
    memory_store,
):
    connection, control_plane = constitution_connection
    history = SqlDeliveryRecordStore(memory_store.engine)
    control_plane.delivery_recorder = DeliveryRecorder(history, "always")
    with pytest.raises(KynoHistoryError):
        connection.get_constitution("example", version=9)
    assert history.list()["items"] == []
