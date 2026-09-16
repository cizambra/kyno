import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from kyno.sdk import KynoConnection, history
from kyno.sdk.errors import KynoHistoryError, KynoRefusedError, KynoUnavailableError
from kyno.wire.models import DetailLevel


def reply(payload, *, error=False):
    return SimpleNamespace(
        isError=error, content=[SimpleNamespace(text=payload if error else json.dumps(payload))]
    )


@pytest.mark.parametrize("record_id", [None, 1, True, "", "   "])
def test_given_invalid_record_id_when_getting_history_then_request_is_not_sent(record_id):
    runner = Mock()
    with pytest.raises(ValueError, match="record_id"):
        history.get_delivery_record(runner, record_id)
    runner.call.assert_not_called()


@pytest.mark.parametrize("payload", [{}, [], {"served_version": "1"}, None])
def test_given_malformed_record_when_getting_history_then_unavailable_is_raised(payload):
    runner = Mock()
    runner.call.return_value = reply(payload)
    with pytest.raises(KynoUnavailableError, match="bad reply"):
        history.get_delivery_record(runner, "record-1")


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"items": {}, "next_cursor": None},
        {"items": [], "next_cursor": True},
        {"items": [{}], "next_cursor": None},
    ],
)
def test_given_malformed_page_when_listing_history_then_unavailable_is_raised(payload):
    runner = Mock()
    runner.call.return_value = reply(payload)
    with pytest.raises(KynoUnavailableError, match="bad reply"):
        history.list_delivery_records(runner)


@pytest.mark.parametrize("operation", ["get_delivery_record", "list_delivery_records"])
def test_given_mcp_error_when_reading_history_then_sdk_exception_contains_the_server_error_text(
    operation,
):
    runner = Mock()
    runner.call.return_value = reply("delivery history is not configured", error=True)
    arguments = {"record_id": "record-1"} if operation == "get_delivery_record" else {}
    with pytest.raises(KynoHistoryError, match="delivery history is not configured"):
        getattr(history, operation)(runner, **arguments)


@pytest.mark.parametrize("failure", [KynoUnavailableError("offline"), KynoRefusedError("403")])
@pytest.mark.parametrize("operation", ["get_delivery_record", "list_delivery_records"])
def test_given_transport_failure_when_reading_history_then_original_failure_is_preserved(
    failure, operation
):
    runner = Mock()
    runner.call.side_effect = failure
    with pytest.raises(type(failure)) as raised:
        arguments = {"record_id": "record-1"} if operation == "get_delivery_record" else {}
        getattr(history, operation)(runner, **arguments)
    assert raised.value is failure


def test_given_empty_content_when_reading_history_then_unavailable_is_raised():
    runner = Mock()
    runner.call.return_value = SimpleNamespace(isError=False, content=[])
    with pytest.raises(KynoUnavailableError, match="bad reply"):
        history.get_delivery_record(runner, "record-1")


@pytest.mark.parametrize(
    "filters, expected_arguments",
    [
        ({}, {"limit": 50}),
        (
            {
                "correlation_id": "run-42",
                "constitution": "support",
                "since": "2026-01-01T00:00:00Z",
                "until": "2026-02-01T00:00:00Z",
                "after": 0,
                "limit": 1,
            },
            {
                "correlation_id": "run-42",
                "constitution": "support",
                "since": "2026-01-01T00:00:00Z",
                "until": "2026-02-01T00:00:00Z",
                "after": 0,
                "limit": 1,
            },
        ),
    ],
    ids=["default-limit-without-filters", "all-filters-including-zero-cursor"],
)
def test_given_list_filters_when_querying_the_connection_then_mcp_receives_the_exact_arguments(
    filters, expected_arguments
):
    session = SimpleNamespace(
        call_tool=AsyncMock(return_value=reply({"items": [], "next_cursor": None}))
    )
    runner = Mock()
    runner.call.side_effect = lambda operation: asyncio.run(operation(session))

    assert KynoConnection(runner).list_delivery_records(**filters) == {
        "items": [],
        "next_cursor": None,
    }

    session.call_tool.assert_awaited_once_with("list_delivery_records", expected_arguments)


@pytest.mark.parametrize("version", [-1, True, "1", 1.5, None])
def test_given_invalid_version_when_reading_direction_then_request_is_not_sent(version):
    runner = Mock()
    with pytest.raises(ValueError, match="version"):
        history.get_direction_version(runner, version)
    runner.call.assert_not_called()


def test_given_version_zero_when_reading_direction_then_empty_full_direction_returns():
    runner = Mock()
    direction = history.get_direction_version(runner, 0, "example")
    assert direction.version == 0
    assert direction.constitution == "example"
    assert direction.mission == ""
    assert direction.principles == ()
    assert direction.context is DetailLevel.FULL
    runner.call.assert_not_called()


def test_given_requested_version_when_reading_direction_then_exact_export_bounds_are_sent():
    session = SimpleNamespace(call_tool=AsyncMock(return_value=reply([])))
    runner = Mock()
    runner.call.side_effect = lambda callback: asyncio.run(callback(session))
    assert history.get_direction_version(runner, 3, "example") is None
    session.call_tool.assert_awaited_once_with(
        "export_versions", {"constitution": "example", "from_version": 3, "to_version": 3}
    )


@pytest.mark.parametrize(
    "rows",
    [
        {},
        [None],
        [{"version": 1}],
        [{"version": 2, "mission": "M", "declaration": "D", "principles": []}],
        [{"version": True, "mission": "M", "declaration": "D", "principles": []}],
        [{"version": 1, "mission": "M", "declaration": "D", "principles": []}] * 2,
        [{"version": 1, "mission": "M", "declaration": "D", "principles": [{}]}],
        [
            {
                "version": 1,
                "mission": "M",
                "declaration": "D",
                "principles": [{"title": "", "description": ""}],
            }
        ],
    ],
)
def test_given_malformed_version_reply_when_reading_direction_then_unavailable_is_raised(rows):
    runner = Mock()
    runner.call.return_value = reply(rows)
    with pytest.raises(KynoUnavailableError):
        history.get_direction_version(runner, 1)


def test_given_oversized_history_reply_when_reading_then_unavailable_is_raised(monkeypatch):
    monkeypatch.setattr(history, "MAX_REPLY_CHARS", 1)
    runner = Mock()
    runner.call.return_value = reply([])
    with pytest.raises(KynoUnavailableError, match="limit"):
        history.get_direction_version(runner, 1)


@pytest.mark.parametrize("constitution", [None, 1, "", "   "])
def test_given_invalid_constitution_when_reading_version_then_request_is_not_sent(constitution):
    runner = Mock()
    with pytest.raises(ValueError, match="constitution"):
        history.get_direction_version(runner, 1, constitution)
    runner.call.assert_not_called()
