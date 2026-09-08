import asyncio
import threading
from contextlib import asynccontextmanager

import pytest

from kyno.errors import KynoRefusedError, KynoUnavailableError
from kyno.sdk.client import KynoBinding, SessionRunner, http_session


class _Refused(Exception):
    """What an HTTP client raises for a status it will not follow: the
    exception carries the response that produced it."""

    def __init__(self, status, body=""):
        super().__init__(f"Client error '{status}'")
        self.response = _Response(status, body)


def refused_with_body(status, body):
    """A refusal whose response body can still be read."""
    return _Refused(status, body)


def refused_with_an_unreadable_body(status):
    """A refusal whose response body cannot be read, because the
    transport closed the stream before anything asked for it."""
    return _Refused(status, body=None)


class _Response:
    def __init__(self, status, body=""):
        self.status_code = status
        self._body = body

    @property
    def text(self):
        if self._body is None:
            raise RuntimeError("the stream is closed")
        return self._body

    def read(self):
        if self._body is None:
            raise RuntimeError("the stream is closed")
        return self._body.encode()


def _runner_whose_session_ends_during_a_call(failure):
    """A runner whose session ends while a call is in flight, the way a
    server refusal ends it: the transport's task group raises, the loop
    unwinds, and the pending call is cancelled with it."""

    @asynccontextmanager
    async def connect(message_handler=None):
        calling = asyncio.Event()

        async def fail_once_the_call_starts():
            await calling.wait()
            raise failure

        class _Session:
            async def slow_call(self):
                calling.set()
                await asyncio.sleep(30)

        async with asyncio.TaskGroup() as group:
            group.create_task(fail_once_the_call_starts())
            yield _Session()

    runner = SessionRunner(connect, timeout=5.0)
    runner.start()
    return runner


def _fake_transport(monkeypatch) -> dict:
    """Stands in for the network so the header wiring is checked, not mocked."""
    import mcp
    import mcp.client.streamable_http as streamable_http

    captured: dict = {}

    @asynccontextmanager
    async def fake_client(url, headers=None):
        captured["url"] = url
        captured["headers"] = headers
        yield ("read", "write", "session-id")

    class FakeSession:
        def __init__(self, read, write, message_handler=None):
            captured["message_handler"] = message_handler

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

        async def initialize(self):
            captured["initialized"] = True

    monkeypatch.setattr(streamable_http, "streamablehttp_client", fake_client)
    monkeypatch.setattr(mcp, "ClientSession", FakeSession)
    return captured


def test_given_a_runner_that_cannot_connect_when_starting_then_it_fails_loudly():
    @asynccontextmanager
    async def connect(message_handler=None):
        raise OSError("connection refused")
        yield  # pragma: no cover - unreachable, keeps this a generator

    with pytest.raises(KynoUnavailableError):
        SessionRunner(connect).start()


def test_given_a_401_inside_nested_groups_when_starting_then_the_error_reads_401_unauthorized():
    # The async stack buries an HTTP refusal inside nested exception groups
    # whose own text only says "unhandled errors in a TaskGroup". The
    # person at the terminal gets the status line instead.
    @asynccontextmanager
    async def connect(message_handler=None):
        refusal = refused_with_an_unreadable_body(401)
        raise ExceptionGroup("unhandled", [ExceptionGroup("nested", [refusal])])
        yield  # pragma: no cover - unreachable, keeps this a generator

    with pytest.raises(KynoRefusedError, match="401 unauthorized"):
        SessionRunner(connect).start()


def test_given_a_failure_with_extra_message_lines_when_starting_then_the_error_keeps_the_first():
    # httpx appends a documentation link on a second line.
    @asynccontextmanager
    async def connect(message_handler=None):
        raise OSError("connection refused\nFor more information check: https://example.com")
        yield  # pragma: no cover - unreachable, keeps this a generator

    with pytest.raises(KynoUnavailableError, match="connection refused$"):
        SessionRunner(connect).start()


def test_given_a_body_that_can_be_read_when_building_the_message_then_it_is_the_body():
    from kyno.sdk.client import _refusal_text

    failure = refused_with_body(403, "forbidden: this token's scope does not cover 'set_direction'")

    # A refusal reaches this function inside the group the transport raised.
    line = _refusal_text(ExceptionGroup("unhandled", [failure]))

    assert line == "forbidden: this token's scope does not cover 'set_direction'"


def test_given_a_body_that_cannot_be_read_when_building_the_message_then_it_is_the_status_line():
    from kyno.sdk.client import _refusal_text

    failure = refused_with_an_unreadable_body(401)

    assert _refusal_text(ExceptionGroup("unhandled", [failure])) == "401 unauthorized"


def test_given_a_call_in_flight_when_a_403_ends_the_session_then_the_error_carries_the_body():
    # The refusal arrives after the call is already running, so the call
    # is cancelled rather than answered. Without this path the command
    # exits with no message at all.
    runner = _runner_whose_session_ends_during_a_call(
        refused_with_body(403, "forbidden: this token's scope does not cover 'set_direction'")
    )
    try:
        with pytest.raises(KynoRefusedError, match="scope does not cover"):
            runner.call(lambda session: session.slow_call())
    finally:
        runner.close()


def test_given_a_call_in_flight_when_the_connection_drops_then_it_raises_unavailable_not_refused():
    runner = _runner_whose_session_ends_during_a_call(OSError("connection reset by peer"))
    try:
        with pytest.raises(KynoUnavailableError, match="ended mid-call: connection reset") as seen:
            runner.call(lambda session: session.slow_call())
        assert not isinstance(seen.value, KynoRefusedError)
    finally:
        runner.close()


def test_given_a_call_in_flight_when_the_runner_is_closed_then_it_reports_the_session_ended():
    # Closing ends the session without an error, so the cancelled call
    # has nothing to describe and says only that the session ended.
    started = threading.Event()

    @asynccontextmanager
    async def connect(message_handler=None):
        class _Session:
            async def slow_call(self):
                started.set()
                await asyncio.sleep(30)

        yield _Session()

    # A short patience, so this test costs milliseconds either way.
    runner = SessionRunner(connect, timeout=0.5)
    runner.start()
    closer = threading.Thread(target=lambda: (started.wait(5), runner.close()), daemon=True)
    closer.start()
    try:
        with pytest.raises(KynoUnavailableError, match="ended mid-call"):
            runner.call(lambda session: session.slow_call())
    finally:
        closer.join(timeout=5)


def test_given_a_failure_with_no_message_when_summarizing_then_its_type_stands_in():
    from kyno.sdk.client import _summary

    assert _summary(ExceptionGroup("unhandled", [OSError()])) == "OSError"


def test_given_a_500_when_building_the_message_then_there_is_no_refusal_message():
    # 401 and 403 mean the credential was turned away. A 500 is the
    # server failing, and must not be reported as a token problem.
    from kyno.sdk.client import _refusal_text

    assert _refusal_text(ExceptionGroup("unhandled", [refused_with_body(500, "boom")])) is None


def test_given_two_failures_in_one_group_when_summarizing_then_they_join_with_a_semicolon():
    from kyno.sdk.client import _summary

    line = _summary(ExceptionGroup("unhandled", [OSError("no route"), ValueError("bad reply")]))

    assert line == "no route; bad reply"


def test_given_no_endpoint_when_building_an_http_session_then_it_is_refused():
    with pytest.raises(KynoUnavailableError):
        http_session(KynoBinding())


async def test_given_a_token_when_the_http_session_connects_then_it_goes_as_a_bearer_header(
    monkeypatch,
):
    captured = _fake_transport(monkeypatch)

    connect = http_session(KynoBinding(endpoint="https://kyno.internal/mcp", token="secret"))
    async with connect():
        pass

    assert captured["url"] == "https://kyno.internal/mcp"
    assert captured["headers"] == {"Authorization": "Bearer secret"}
    assert captured["initialized"] is True


async def test_given_no_token_when_the_http_session_connects_then_no_auth_header_goes(monkeypatch):
    captured = _fake_transport(monkeypatch)

    connect = http_session(KynoBinding(endpoint="https://kyno.internal/mcp"))
    async with connect(message_handler="handler"):
        pass

    assert captured["headers"] is None
    assert captured["message_handler"] == "handler"
