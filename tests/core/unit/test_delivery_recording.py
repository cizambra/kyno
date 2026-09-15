from copy import deepcopy
from unittest.mock import Mock

import pytest

from kyno.delivery import RecordingPolicy
from kyno.delivery_recording import DeliveryRecorder
from kyno.store.delivery_record import SqlDeliveryRecordStore


@pytest.fixture
def store():
    return Mock(spec=SqlDeliveryRecordStore, append=Mock(return_value="delivery-1"))


def test_given_default_policy_when_recording_then_append_is_disabled(store):
    result = DeliveryRecorder(store).record(
        {"version": 1}, operation="get_constitution", constitution="team", arguments={}
    )
    assert result == {"status": "disabled", "record_id": None}
    store.append.assert_not_called()


@pytest.mark.parametrize("policy", list(RecordingPolicy))
def test_given_invalid_context_when_recording_then_validation_propagates(store, policy):
    with pytest.raises(ValueError, match="correlation_id"):
        DeliveryRecorder(store, policy).record(
            {"version": 1},
            operation="get_constitution",
            constitution="team",
            arguments={"correlation_id": 3},
        )
    store.append.assert_not_called()


@pytest.mark.parametrize(
    "operation, supplied, expected",
    [
        ("get_constitution", {}, {"detail": "compact"}),
        ("get_constitution", {"detail": "full"}, {"detail": "full"}),
        ("get_changes_since", {"known_version": 1}, {"detail": "compact", "known_version": 1}),
        (
            "get_changes_since",
            {"known_version": 1, "detail": "full"},
            {"detail": "full", "known_version": 1},
        ),
        ("get_principles", {}, {"detail": "titles"}),
        ("get_principles", {"detail": "full"}, {"detail": "full"}),
        ("get_principle", {"title": "Care"}, {"title": "Care"}),
        ("get_mission", {}, {}),
        ("get_declaration", {}, {}),
    ],
)
def test_given_read_arguments_when_recording_then_only_effective_arguments_are_appended(
    store, operation, supplied, expected
):
    arguments = {"correlation_id": "session", "metadata": {"nested": [1]}, "extra": object()}
    arguments.update(supplied)
    direction = {"version": 2, "current_version": 2, "principles": [{"title": "Care"}]}
    original = deepcopy(direction)
    requester = {"id": 1, "name": "reader", "scope": "read"}
    result = DeliveryRecorder(store, "always").record(
        direction,
        operation=operation,
        constitution="team",
        arguments=arguments,
        requester=requester,
    )
    assert result == {"status": "recorded", "record_id": "delivery-1"}
    store.append.assert_called_once_with(
        direction,
        operation=operation,
        constitution="team",
        arguments=expected,
        context={"correlation_id": "session", "metadata": {"nested": [1]}},
        requester=requester,
        timeout_seconds=1.0,
    )
    assert direction == original


def test_given_irrelevant_selection_arguments_when_recording_then_they_are_ignored(store):
    DeliveryRecorder(store, "always").record(
        {"version": 1},
        operation="get_mission",
        constitution="team",
        arguments={"known_version": object(), "detail": object(), "title": object()},
    )
    assert store.append.call_args.kwargs["arguments"] == {}


def test_given_append_failure_when_recording_then_failure_is_reported_without_sensitive_logs(
    store, caplog
):
    store.append.side_effect = RuntimeError("secret-token-and-direction")
    direction = {"version": 1, "mission": "private mission"}
    original = deepcopy(direction)
    result = DeliveryRecorder(store, "always").record(
        direction, operation="get_constitution", constitution="team", arguments={}
    )
    assert result == {"status": "failed", "record_id": None}
    assert direction == original
    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.message == "delivery_recording_failed"
    assert record.error_type == "RuntimeError"
    assert record.exc_info is None
    assert "secret-token" not in caplog.text
    assert "private mission" not in caplog.text


def test_given_invalid_policy_when_constructing_then_it_is_rejected(store):
    with pytest.raises(ValueError):
        DeliveryRecorder(store, "sometimes")


def test_given_custom_recording_timeout_when_recording_then_the_store_uses_that_limit(store):
    DeliveryRecorder(store, "always", timeout_seconds=0.25).record(
        {"version": 0}, operation="get_mission", constitution="missing", arguments={}
    )
    assert store.append.call_args.kwargs["timeout_seconds"] == 0.25


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf"), True])
def test_given_invalid_recording_timeout_when_building_recorder_then_it_is_rejected(store, timeout):
    with pytest.raises(ValueError, match="positive finite"):
        DeliveryRecorder(store, "always", timeout_seconds=timeout)
