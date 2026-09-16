"""SDK history queries round-trip through the real MCP server and delivery store."""

import pytest

from kyno.sdk.errors import KynoHistoryError, KynoUnavailableError
from kyno.store.delivery_record import SqlDeliveryRecordStore


@pytest.fixture
def history_connection(mcp_connection):
    connection, control_plane = mcp_connection
    history = SqlDeliveryRecordStore(control_plane._store.engine)
    control_plane.delivery_record_store = history
    identifiers = []
    for correlation_id in ["run-1", "run-2", "run-1"]:
        identifiers.append(
            history.append(
                {"current_version": 0, "delta": ["Saved comparison"]},
                operation="get_changes_since",
                constitution="default",
                arguments={"known_version": 0, "detail": "full"},
                context={"correlation_id": correlation_id, "metadata": {"step": 1}},
            )
        )
    return connection, history, identifiers


def test_given_saved_record_when_reading_with_sdk_then_version_reference_and_delta_return(
    history_connection,
):
    connection, history, identifiers = history_connection
    record = connection.get_delivery_record(identifiers[0])
    assert record == history.get(identifiers[0])
    assert record["delta"] == ["Saved comparison"]
    assert record["metadata"] == {"step": 1}


def test_given_filtered_history_when_advancing_cursor_then_matching_summaries_return(
    history_connection,
):
    connection, history, identifiers = history_connection
    filters = dict(
        correlation_id="run-1",
        constitution="default",
        since="2000-01-01T00:00:00Z",
        until="9998-01-01T00:00:00Z",
        limit=1,
    )
    first = connection.list_delivery_records(**filters)
    assert [item["record_id"] for item in first["items"]] == identifiers[:1]
    assert "delta" not in first["items"][0]
    last = connection.list_delivery_records(**filters, after=first["next_cursor"])
    assert [item["record_id"] for item in last["items"]] == identifiers[2:]
    assert last["next_cursor"] is None
    assert len(history.list()["items"]) == 3


@pytest.mark.parametrize(
    "filters",
    [
        {"correlation_id": "absent"},
        {"constitution": "absent"},
        {"since": "9998-01-01T00:00:00Z"},
        {"until": "2000-01-01T00:00:00Z"},
    ],
    ids=["correlation", "constitution", "since", "until"],
)
def test_given_nonmatching_filter_when_listing_with_sdk_then_empty_page_returns(
    history_connection, filters
):
    connection, _, _ = history_connection
    assert connection.list_delivery_records(**filters) == {
        "items": [],
        "next_cursor": None,
    }


def test_given_unknown_record_when_getting_with_sdk_then_history_error_is_actionable(
    history_connection,
):
    connection, _, _ = history_connection
    with pytest.raises(KynoHistoryError, match="delivery record not found"):
        connection.get_delivery_record("absent")


def test_given_invalid_limit_when_listing_with_sdk_then_history_error_is_actionable(
    history_connection,
):
    connection, _, _ = history_connection
    with pytest.raises(KynoHistoryError, match="minimum"):
        connection.list_delivery_records(limit=0)


@pytest.mark.parametrize("operation", ["get_delivery_record", "list_delivery_records"])
def test_given_a_prior_history_read_when_disconnected_then_read_raises_instead_of_returning_cache(
    history_connection, operation
):
    connection, _, identifiers = history_connection
    arguments = {"record_id": identifiers[0]} if operation == "get_delivery_record" else {}
    read = getattr(connection, operation)
    assert read(**arguments)
    connection.close()
    with pytest.raises(KynoUnavailableError):
        read(**arguments)


@pytest.mark.parametrize("operation", ["get_delivery_record", "list_delivery_records"])
def test_given_history_not_configured_when_reading_with_sdk_then_history_error_explains_why(
    mcp_connection, operation
):
    connection, _ = mcp_connection
    arguments = {"record_id": "record-1"} if operation == "get_delivery_record" else {}
    with pytest.raises(KynoHistoryError, match="not configured"):
        getattr(connection, operation)(**arguments)


def test_given_a_version_one_record_when_direction_advances_then_sdk_returns_the_saved_reference(
    mcp_connection,
):
    connection, control_plane = mcp_connection
    history = SqlDeliveryRecordStore(control_plane._store.engine)
    control_plane.delivery_record_store = history
    control_plane.set_direction(mission="Help customers.", change_note="Initial direction")
    identifier = history.append(
        {"version": 1},
        operation="get_mission",
        constitution="default",
        arguments={},
        context={"correlation_id": None, "metadata": {}},
    )
    saved_record = history.get(identifier)
    control_plane.set_direction(mission="Protect trust.", change_note="New priority")

    record = connection.get_delivery_record(identifier)

    assert record == saved_record
    assert record["constitution_id"] is not None
    assert record["served_version"] == 1
    assert record["delta"] is None
