import logging

from kyno.errors import CoherenceError, KynoUnavailableError
from kyno.sdk.policy import (
    UNCHECKED,
    GatePolicy,
    LogSink,
    PullPolicy,
    RecordingSink,
    TelemetryEvent,
)


def test_given_no_choice_when_building_the_policy_then_the_default_is_fail_open():
    assert GatePolicy().fail_closed is False
    assert PullPolicy().fail_closed is False
    assert GatePolicy(fail_closed=True).fail_closed is True


def test_given_events_when_the_recording_sink_takes_them_then_their_order_is_kept():
    sink = RecordingSink()
    sink.emit(TelemetryEvent(kind=UNCHECKED, constitution="eu", version=2, detail="no_source"))
    sink.emit(TelemetryEvent(kind=UNCHECKED, constitution="us", version=1, detail="source_error"))
    assert [e.constitution for e in sink.events] == ["eu", "us"]
    assert sink.events[0].to_dict()["kind"] == UNCHECKED


def test_given_a_degrade_when_the_log_sink_warns_then_the_constitution_and_version_are_named(
    caplog,
):
    with caplog.at_level(logging.WARNING, logger="kyno.adapters"):
        LogSink().emit(TelemetryEvent(kind=UNCHECKED, constitution="eu", version=3, detail="x"))
    assert "eu" in caplog.text and "3" in caplog.text and UNCHECKED in caplog.text


def test_given_the_error_types_when_comparing_then_unavailable_is_a_coherence_error():
    assert issubclass(KynoUnavailableError, CoherenceError)
