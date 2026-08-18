import logging

from kyno.adapters.core.policy import (
    UNCHECKED,
    GatePolicy,
    LogSink,
    PullPolicy,
    RecordingSink,
    TelemetryEvent,
)
from kyno.errors import CoherenceError, KynoUnavailableError


def test_defaults_are_fail_open():
    assert GatePolicy().fail_closed is False
    assert PullPolicy().fail_closed is False
    assert GatePolicy(fail_closed=True).fail_closed is True


def test_recording_sink_keeps_events_in_order():
    sink = RecordingSink()
    sink.emit(TelemetryEvent(kind=UNCHECKED, constitution="eu", version=2, detail="no_source"))
    sink.emit(TelemetryEvent(kind=UNCHECKED, constitution="us", version=1, detail="source_error"))
    assert [e.constitution for e in sink.events] == ["eu", "us"]
    assert sink.events[0].to_dict()["kind"] == UNCHECKED


def test_log_sink_warns_with_the_constitution_and_version(caplog):
    with caplog.at_level(logging.WARNING, logger="kyno.adapters"):
        LogSink().emit(TelemetryEvent(kind=UNCHECKED, constitution="eu", version=3, detail="x"))
    assert "eu" in caplog.text and "3" in caplog.text and UNCHECKED in caplog.text


def test_unavailable_is_a_coherence_error():
    assert issubclass(KynoUnavailableError, CoherenceError)
