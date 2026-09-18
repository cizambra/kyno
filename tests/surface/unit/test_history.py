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


@pytest.mark.parametrize(
    "operation", ["get_delivery_record", "list_delivery_records", "get_constitution"]
)
def test_given_mcp_error_when_reading_history_then_sdk_exception_contains_the_server_error_text(
    operation,
):
    runner = Mock()
    runner.call.return_value = reply("delivery history is not configured", error=True)
    arguments = {"record_id": "record-1"} if operation == "get_delivery_record" else {}
    with pytest.raises(KynoHistoryError, match="delivery history is not configured"):
        getattr(history, operation)(runner, **arguments)


@pytest.mark.parametrize("failure", [KynoUnavailableError("offline"), KynoRefusedError("403")])
@pytest.mark.parametrize(
    "operation", ["get_delivery_record", "list_delivery_records", "get_constitution"]
)
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
        ({"constitution_key": " support "}, {"constitution_key": "support", "limit": 50}),
        ({"constitution_key": None}, {"limit": 50}),
        (
            {
                "correlation_id": "run-42",
                "constitution_key": "support",
                "since": "2026-01-01T00:00:00Z",
                "until": "2026-02-01T00:00:00Z",
                "after": 0,
                "limit": 1,
            },
            {
                "correlation_id": "run-42",
                "constitution_key": "support",
                "since": "2026-01-01T00:00:00Z",
                "until": "2026-02-01T00:00:00Z",
                "after": 0,
                "limit": 1,
            },
        ),
    ],
    ids=[
        "default-limit-without-filters",
        "normalized-key-filter",
        "null-key-filter",
        "all-filters-including-zero-cursor",
    ],
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


@pytest.mark.parametrize("constitution_key", ["", "   ", "Upper"])
def test_given_invalid_key_filter_when_connection_lists_history_then_request_is_not_sent(
    constitution_key,
):
    runner = Mock()

    with pytest.raises(ValueError, match="constitution key"):
        KynoConnection(runner).list_delivery_records(constitution_key=constitution_key)

    runner.call.assert_not_called()


@pytest.mark.parametrize("version", [-1, True, "1", 1.5])
def test_given_invalid_version_when_get_constitution_is_called_then_request_is_not_sent(version):
    runner = Mock()
    with pytest.raises(ValueError, match="version"):
        history.get_constitution(runner, version=version)
    runner.call.assert_not_called()


@pytest.mark.parametrize("version", [None, 0, 3])
@pytest.mark.parametrize("detail", list(DetailLevel))
def test_given_version_selection_when_get_constitution_is_called_then_exact_tool_arguments_are_sent(
    version, detail
):
    returned_version = 3 if version is None else version
    payload = {"version": returned_version, "mission": "", "principles": []}
    session = SimpleNamespace(call_tool=AsyncMock(return_value=reply(payload)))
    runner = Mock()
    runner.call.side_effect = lambda callback: asyncio.run(callback(session))
    result = KynoConnection(runner).get_constitution(
        constitution_key="example", version=version, detail=detail
    )
    assert result.version == returned_version
    assert result.detail is detail
    expected = {"constitution_key": "example", "detail": detail.value}
    if version is not None:
        expected["version"] = version
    session.call_tool.assert_awaited_once_with("get_constitution", expected)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        [None],
        {"version": 1},
        {"version": 2, "mission": "M", "declaration": "D", "principles": []},
        {"version": -1, "mission": "M", "declaration": "D", "principles": []},
        {"version": True, "mission": "M", "declaration": "D", "principles": []},
        [{"version": 1, "mission": "M", "declaration": "D", "principles": []}] * 2,
        {"version": 1, "mission": "M", "declaration": "D", "principles": [{}]},
        {
            "version": 1,
            "mission": "M",
            "declaration": "D",
            "principles": [{"title": "", "description": ""}],
        },
    ],
)
def test_given_malformed_reply_when_get_constitution_is_called_then_unavailable_is_raised(payload):
    runner = Mock()
    runner.call.return_value = reply(payload)
    with pytest.raises(KynoUnavailableError):
        history.get_constitution(runner, version=1)


@pytest.mark.parametrize("constitution", [1, "", "   "])
def test_given_invalid_name_when_get_constitution_is_called_then_request_is_not_sent(constitution):
    runner = Mock()
    with pytest.raises(ValueError, match="constitution"):
        history.get_constitution(runner, constitution, version=1)
    runner.call.assert_not_called()


@pytest.mark.parametrize("key", ["", " ", "Upper", "a" * 201])
def test_given_invalid_key_filter_when_listing_history_then_request_is_not_sent(key):
    runner = Mock()
    with pytest.raises(ValueError, match="constitution key"):
        history.list_delivery_records(runner, constitution=key)
    runner.call.assert_not_called()


@pytest.mark.parametrize(
    "key, expected", [(None, "default"), (" a" + "b" * 199 + " ", "a" + "b" * 199)]
)
def test_given_normalizable_key_when_get_constitution_runs_then_request_uses_normalized_key(
    key, expected
):
    session = SimpleNamespace(
        call_tool=AsyncMock(return_value=reply({"version": 0, "mission": "", "principles": []}))
    )
    runner = Mock()
    runner.call.side_effect = lambda operation: asyncio.run(operation(session))
    direction = history.get_constitution(runner, key)
    assert direction.constitution_key == expected
    session.call_tool.assert_awaited_once_with(
        "get_constitution", {"constitution_key": expected, "detail": "compact"}
    )


@pytest.mark.parametrize("detail", ["unknown", None, 1])
@pytest.mark.parametrize("version", [0, 1])
def test_given_invalid_detail_when_get_constitution_is_called_then_request_is_not_sent(
    detail, version
):
    runner = Mock()
    with pytest.raises(ValueError, match="detail"):
        KynoConnection(runner).get_constitution(version=version, detail=detail)
    runner.call.assert_not_called()
