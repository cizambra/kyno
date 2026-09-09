import logging

from kyno.sdk.telemetry import EventType, LogSink, RecordingSink, TelemetryEvent


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
