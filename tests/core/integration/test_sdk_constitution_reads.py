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
def test_given_version_and_context_when_get_constitution_is_called_then_requested_content_returns(
    constitution_connection, context, version
):
    connection, control_plane = constitution_connection
    original = connection.binder("example", context=context).bind()
    if version is not None:
        control_plane.set_direction(
            mission="New mission", change_note="Updated", constitution="example"
        )
    binder = connection.binder("example", context=context)
    current = binder.bind()

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
    connection.close()
    assert binder.bind() is current


def test_given_updates_when_get_constitution_omits_version_then_current_compact_direction_returns(
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


@pytest.mark.parametrize("version", [None, 1])
def test_given_two_constitutions_when_get_constitution_is_called_then_requested_direction_returns(
    constitution_connection, version
):
    connection, control_plane = constitution_connection
    control_plane.set_direction(
        mission="Default mission", change_note="Initial", constitution="default"
    )

    direction = connection.get_constitution("example", version=version)
    default_direction = connection.get_constitution(version=version)

    assert direction.constitution == "example"
    assert direction.mission == "Original mission"
    assert default_direction.constitution == "default"
    assert default_direction.mission == "Default mission"
    assert direction.version == default_direction.version == 1


@pytest.mark.parametrize("context", list(DetailLevel))
def test_given_unwritten_constitution_when_get_constitution_is_called_then_empty_direction_returns(
    constitution_connection, context
):
    connection, _ = constitution_connection

    direction = connection.get_constitution("unwritten", context=context)

    assert direction.constitution == "unwritten"
    assert direction.version == 0
    assert direction.mission == direction.declaration == ""
    assert direction.principles == direction.change_notes == direction.delta == ()
    assert direction.context is context


@pytest.mark.parametrize("constitution, version", [("example", 2), ("unknown", 1)])
def test_given_missing_version_when_get_constitution_is_called_then_version_not_found_is_raised(
    constitution_connection, constitution, version
):
    connection, _ = constitution_connection
    with pytest.raises(KynoHistoryError, match="version.*not found"):
        connection.get_constitution(constitution, version=version)


@pytest.mark.parametrize("context", list(DetailLevel))
def test_given_live_direction_when_get_constitution_requests_zero_then_empty_direction_returns(
    constitution_connection, context
):
    connection, _ = constitution_connection
    direction = connection.get_constitution("example", version=0, context=context)
    assert direction.version == 0
    assert direction.mission == direction.declaration == ""
    assert direction.principles == ()
    assert direction.context is context


@pytest.mark.parametrize("version, served_version", [(None, 2), (1, 1), (0, 0)])
def test_given_recording_enabled_when_get_constitution_is_called_then_selected_version_is_recorded(
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
    assert record["last_seen_version"] is None
    assert record["operation"] == "get_constitution"
    assert record["detail_level"] == "compact"


def test_given_missing_version_when_get_constitution_is_called_then_no_delivery_is_recorded(
    constitution_connection,
    memory_store,
):
    connection, control_plane = constitution_connection
    history = SqlDeliveryRecordStore(memory_store.engine)
    control_plane.delivery_recorder = DeliveryRecorder(history, "always")
    with pytest.raises(KynoHistoryError):
        connection.get_constitution("example", version=9)
    assert history.list()["items"] == []
