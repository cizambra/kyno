import logging

import pytest

from kyno.sdk.telemetry import EventType, LogSink, RecordingSink, TelemetryEvent


def test_given_a_string_event_type_when_creating_an_event_then_it_becomes_the_matching_type():
    event = TelemetryEvent(kind="unchecked", constitution="eu", version=1)

    assert event.kind is EventType.UNCHECKED


def test_given_an_unknown_event_type_when_creating_an_event_then_it_is_refused():
    with pytest.raises(ValueError, match="unknown"):
        TelemetryEvent(kind="unknown", constitution="eu", version=1)


def test_given_a_typed_event_when_serializing_then_its_type_is_a_plain_string():
    event = TelemetryEvent(kind=EventType.UNCHECKED, constitution="eu", version=1)

    payload = event.to_dict()

    assert payload["kind"] == "unchecked"
    assert type(payload["kind"]) is str


def test_given_events_when_the_recording_sink_takes_them_then_their_order_is_kept():
    sink = RecordingSink()
    sink.emit(
        TelemetryEvent(
            kind=EventType.UNCHECKED,
            constitution="eu",
            version=2,
            detail="no_source",
        )
    )
    sink.emit(
        TelemetryEvent(
            kind=EventType.UNCHECKED,
            constitution="us",
            version=1,
            detail="source_error",
        )
    )

    assert [event.constitution for event in sink.events] == ["eu", "us"]
    assert sink.events[0].to_dict()["kind"] == "unchecked"


def test_given_a_degrade_when_the_log_sink_warns_then_the_constitution_and_version_are_named(
    caplog,
):
    with caplog.at_level(logging.WARNING, logger="kyno.adapters"):
        LogSink().emit(
            TelemetryEvent(
                kind=EventType.UNCHECKED,
                constitution="eu",
                version=3,
                detail="x",
            )
        )

    assert "eu" in caplog.text and "3" in caplog.text and "unchecked" in caplog.text
