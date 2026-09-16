import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from kyno.sdk import history
from kyno.sdk.errors import KynoHistoryError, KynoRefusedError, KynoUnavailableError


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
def test_given_tool_error_when_reading_history_then_history_error_preserves_message(operation):
    runner = Mock()
    runner.call.return_value = reply("delivery history is not configured", error=True)
    arguments = {"record_id": "record-1"} if operation == "get_delivery_record" else {}
    with pytest.raises(KynoHistoryError, match="delivery history is not configured"):
        getattr(history, operation)(runner, **arguments)


@pytest.mark.parametrize("failure", [KynoUnavailableError("offline"), KynoRefusedError("403")])
def test_given_transport_failure_when_reading_history_then_original_failure_is_preserved(failure):
    runner = Mock()
    runner.call.side_effect = failure
    with pytest.raises(type(failure)) as raised:
        history.get_delivery_record(runner, "record-1")
    assert raised.value is failure


def test_given_empty_content_when_reading_history_then_unavailable_is_raised():
    runner = Mock()
    runner.call.return_value = SimpleNamespace(isError=False, content=[])
    with pytest.raises(KynoUnavailableError, match="bad reply"):
        history.get_delivery_record(runner, "record-1")
