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
    assert "direction" not in record


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


def test_given_nonmatching_filter_when_listing_with_sdk_then_empty_page_returns(history_connection):
    connection, _, _ = history_connection
    assert connection.list_delivery_records(correlation_id="absent") == {
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


def test_given_closed_connection_when_reading_history_then_unavailable_is_raised(mcp_connection):
    connection, _ = mcp_connection
    connection.close()
    with pytest.raises(KynoUnavailableError):
        connection.list_delivery_records()
