"""What a bad reply from Kyno costs a running host application.

When Kyno is unreachable or answers garbage, the binder falls back to the
last known direction and emits telemetry saying so. Acting on stale direction
is the accepted cost; crashing the host's step is not. That fallback catches
exactly one failure shape, KynoUnavailableError, so these tests force every
way a reply can be wrong and assert each one arrives as that error. A raw
JSONDecodeError or KeyError would skip the fallback and surface inside the
host's agent step instead.
"""

import json

import pytest

from kyno.errors import KynoUnavailableError
from kyno.sdk.binder import DirectionBinder
from kyno.sdk.client import McpDirectionSource
from kyno.sdk.policy import PULL_FAILED_EMPTY, PULL_FAILED_STALE, RecordingSink


class Text:
    def __init__(self, text):
        self.text = text


class Reply:
    def __init__(self, content):
        self.content = content


class ScriptedRunner:
    """Stands in for a live MCP session: every reply is whatever the test
    says it is, including shapes a healthy Kyno would never send."""

    def __init__(self, reply=None, raises=None):
        self.reply = reply
        self.raises = raises

    def call(self, fn):
        if self.raises is not None:
            raise self.raises
        return self.reply


def good_payload(**overrides):
    payload = {
        "current_version": 2,
        "changed": True,
        "mission": "M2",
        "principles": [{"title": "Be honest"}],
        "changed_mission": True,
        "changed_principles": False,
        "change_notes": ["pivot"],
    }
    payload.update(overrides)
    return payload


def source_for(payload_text=None, *, reply=None, raises=None):
    if reply is None and raises is None:
        reply = Reply([Text(payload_text)])
    return McpDirectionSource(ScriptedRunner(reply=reply, raises=raises))


MALFORMED = {
    "not json at all": Reply([Text("not json")]),
    "an empty object": Reply([Text("{}")]),
    "a json list": Reply([Text("[1, 2, 3]")]),
    "json null": Reply([Text("null")]),
    "no content at all": Reply([]),
    "content with no text": Reply([object()]),
    "a missing field": Reply([Text(json.dumps({"current_version": 1}))]),
    "a null mission": Reply([Text(json.dumps(good_payload(mission=None)))]),
    "principles as a string": Reply([Text(json.dumps(good_payload(principles="be honest")))]),
    "a principle with no title": Reply(
        [Text(json.dumps(good_payload(principles=[{"description": "orphan"}])))]
    ),
    "change notes as an object": Reply([Text(json.dumps(good_payload(change_notes={"a": 1})))]),
    "a version that is not a number": Reply(
        [Text(json.dumps(good_payload(current_version="soon")))]
    ),
    "a negative version": Reply([Text(json.dumps(good_payload(current_version=-1)))]),
}


@pytest.mark.parametrize("shape", sorted(MALFORMED))
def test_given_any_malformed_reply_when_pulling_then_it_arrives_as_unavailable(shape):
    with pytest.raises(KynoUnavailableError, match="bad reply"):
        source_for(reply=MALFORMED[shape]).changes_since(0, "default")


@pytest.mark.parametrize("shape", sorted(MALFORMED))
def test_given_a_malformed_reply_when_a_crew_is_running_then_the_last_direction_carries_it(shape):
    # The whole point: a bad reply costs freshness, not the step.
    sink = RecordingSink()
    runner = ScriptedRunner(reply=Reply([Text(json.dumps(good_payload()))]))
    binder = DirectionBinder(McpDirectionSource(runner), telemetry=sink)
    binder.bind()

    runner.reply = MALFORMED[shape]
    direction = binder.bind()

    assert direction.version == 2 and direction.mission == "M2"
    assert [e.kind for e in sink.events] == [PULL_FAILED_STALE]


@pytest.mark.parametrize("shape", sorted(MALFORMED))
def test_given_a_malformed_reply_and_nothing_cached_when_pulling_then_the_empty_direction_serves(
    shape,
):
    sink = RecordingSink()
    source = McpDirectionSource(ScriptedRunner(reply=MALFORMED[shape]))
    binder = DirectionBinder(source, telemetry=sink)

    direction = binder.bind("eu")

    assert direction.version == 0 and direction.constitution == "eu"
    assert [e.kind for e in sink.events] == [PULL_FAILED_EMPTY]


def test_given_a_protocol_error_from_the_session_when_pulling_then_it_arrives_as_unavailable():
    # McpError, anyio's closed-resource errors, anything the transport raises.
    with pytest.raises(KynoUnavailableError, match="bad reply"):
        source_for(raises=RuntimeError("peer closed the stream")).changes_since(0, "default")


def test_given_an_unavailable_error_when_reading_it_then_its_own_message_is_kept():
    # Already the answer the binder degrades on; re-wrapping it would bury
    # the reason (a timeout, a closed session) under a generic one.
    original = KynoUnavailableError("timed out talking to kyno")
    with pytest.raises(KynoUnavailableError, match="timed out"):
        source_for(raises=original).changes_since(0, "default")


def test_given_an_oversized_reply_when_receiving_then_it_is_refused_before_parsing():
    from kyno.sdk.client import MAX_REPLY_CHARS

    huge = json.dumps(good_payload(mission="x" * (MAX_REPLY_CHARS + 1)))
    with pytest.raises(KynoUnavailableError, match="bad reply"):
        source_for(huge).changes_since(0, "default")


def test_given_a_reply_at_the_size_limit_when_receiving_then_it_is_still_read():
    from kyno.sdk.client import MAX_REPLY_CHARS

    payload = json.dumps(good_payload())
    padded = json.dumps(good_payload(mission="x" * (MAX_REPLY_CHARS - len(payload))))
    assert len(padded) <= MAX_REPLY_CHARS
    assert source_for(padded).changes_since(0, "default").current_version == 2


def test_given_a_version_that_is_text_when_pulling_then_it_never_reaches_the_cell():
    # A str version poisons the cell's monotonic compare permanently: every
    # later int comparison against it raises, so the crew stops binding.
    runner = ScriptedRunner(reply=Reply([Text(json.dumps(good_payload(current_version="99")))]))
    binder = DirectionBinder(McpDirectionSource(runner), telemetry=RecordingSink())

    assert binder.bind().version == 99

    runner.reply = Reply([Text(json.dumps(good_payload(current_version=100)))])
    assert binder.bind().version == 100


def test_given_numbers_in_text_fields_when_pulling_then_they_are_coerced_not_dropped():
    payload = json.dumps(good_payload(mission=7, change_notes=[1, 2]))
    changes = source_for(payload).changes_since(0, "default")
    assert changes.mission == "7"
    assert changes.change_notes == ("1", "2")


def test_given_a_loop_closing_between_check_and_dispatch_when_pulling_then_it_is_unavailable(
    monkeypatch,
):
    # The alive-check and the dispatch cannot be atomic, so the loop can close
    # between them and run_coroutine_threadsafe raises RuntimeError.
    import asyncio

    from kyno.sdk.client import SessionRunner

    def closed(coro, loop):
        raise RuntimeError("Event loop is closed")

    monkeypatch.setattr(asyncio, "run_coroutine_threadsafe", closed)
    runner = SessionRunner(connect=None)
    loop = asyncio.new_event_loop()
    try:
        runner._loop, runner._session = loop, object()
        with pytest.raises(KynoUnavailableError, match="not open"):
            runner.call(lambda session: None)
    finally:
        loop.close()
