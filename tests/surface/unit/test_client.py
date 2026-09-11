import asyncio
import json
import threading
from contextlib import asynccontextmanager, suppress

import pytest

from kyno.sdk.client import KynoBinding, McpDirectionSource, SessionRunner
from kyno.sdk.errors import KynoUnavailableError
from kyno.wire.models import DetailLevel


@pytest.mark.parametrize("session_open", [False, True], ids=["connecting", "connected"])
async def test_given_no_startup_timeout_when_session_task_is_cancelled_then_cancellation_propagates(
    session_open,
):
    entered = asyncio.Event()
    cleaned = asyncio.Event()

    @asynccontextmanager
    async def connect(message_handler=None):
        try:
            entered.set()
            if not session_open:
                await asyncio.Event().wait()
            yield object()
        finally:
            await asyncio.sleep(0)
            cleaned.set()

    runner = SessionRunner(connect)
    task = asyncio.create_task(runner._main())
    try:
        async with asyncio.timeout(5):
            await entered.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert cleaned.is_set()
        assert runner._session is None
        assert runner._finished.is_set()
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


@pytest.mark.parametrize("opens_after_cancellation", [False, True])
@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_given_pending_connection_when_start_times_out_then_cleanup_runs_and_thread_exits(
    monkeypatch, opens_after_cancellation, cleanup_fails
):
    entered = threading.Event()
    cleaned = threading.Event()

    @asynccontextmanager
    async def connect(message_handler=None):
        try:
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                if not opens_after_cancellation:
                    raise
            yield object()
        finally:
            cleaned.set()
            if cleanup_fails:
                raise OSError("connection cleanup failed")

    runner = SessionRunner(connect, timeout=5)

    def timeout_after_connect_starts(timeout):
        assert entered.wait(5), "connection factory never started"
        return False

    monkeypatch.setattr(runner._ready, "wait", timeout_after_connect_starts)
    try:
        with pytest.raises(KynoUnavailableError, match="timed out opening"):
            runner.start()
        assert cleaned.wait(5), "startup did not release the connection"
        runner._thread.join(5)
        assert not runner._thread.is_alive()
        assert runner._session is None
        if cleanup_fails:
            assert isinstance(runner._error, OSError)
    finally:
        if runner._thread.is_alive():
            runner._loop.call_soon_threadsafe(
                lambda: [task.cancel() for task in asyncio.all_tasks(runner._loop)]
            )
            runner.close()


@pytest.mark.parametrize("connection_fails", [False, True], ids=["ready-session", "closed-loop"])
def test_given_completed_startup_when_timeout_is_reported_then_the_session_thread_is_stopped(
    monkeypatch, connection_fails
):
    cleaned = threading.Event()

    @asynccontextmanager
    async def connect(message_handler=None):
        try:
            if connection_fails:
                raise OSError("connection failed")
            yield object()
        finally:
            cleaned.set()

    runner = SessionRunner(connect, timeout=5)
    wait_for_ready = runner._ready.wait

    def timeout_after_startup_finishes(timeout):
        assert wait_for_ready(5), "startup did not complete"
        if connection_fails:
            runner._thread.join(5)
            assert runner._loop.is_closed()
        return False

    monkeypatch.setattr(runner._ready, "wait", timeout_after_startup_finishes)
    try:
        with pytest.raises(KynoUnavailableError, match="timed out opening"):
            runner.start()
        runner._thread.join(5)
        assert not runner._thread.is_alive()
        assert cleaned.is_set()
        assert runner._session is None
    finally:
        runner.close()


def test_given_thread_not_scheduled_when_startup_times_out_then_connection_is_never_opened(
    monkeypatch,
):
    release = threading.Event()
    opened = threading.Event()

    @asynccontextmanager
    async def connect(message_handler=None):
        opened.set()
        yield object()

    runner = SessionRunner(connect, timeout=0)
    run = runner._run

    def delayed_run():
        assert release.wait(5), "test did not release the session thread"
        run()

    monkeypatch.setattr(runner, "_run", delayed_run)
    try:
        with pytest.raises(KynoUnavailableError, match="timed out opening"):
            runner.start()
    finally:
        release.set()
        runner._thread.join(5)
    assert not runner._thread.is_alive()
    assert not opened.is_set()
    assert runner._finished.is_set()


def test_given_no_name_when_building_a_binding_then_the_default_constitution_is_used():
    binding = KynoBinding()
    assert binding.endpoint is None
    assert binding.endpoint is None and binding.token is None


def test_given_a_built_binding_when_repointing_then_it_is_refused():
    binding = KynoBinding()
    with pytest.raises(Exception):  # noqa: B017 - frozen dataclass raises FrozenInstanceError
        binding.endpoint = "https://elsewhere/mcp"


def test_given_a_binding_when_reading_its_repr_then_the_token_is_never_there():
    # Bindings travel into logs and tracebacks; the credential must not.
    binding = KynoBinding(endpoint="https://kyno.internal/mcp", token="hunter2")
    assert "hunter2" not in repr(binding)
    assert "kyno.internal" in repr(binding)


def test_given_two_bindings_with_one_wiring_when_comparing_then_they_are_equal_and_hashable():
    wiring = {"endpoint": "https://kyno.internal/mcp", "token": "t"}
    assert KynoBinding(**wiring) == KynoBinding(**wiring)
    assert len({KynoBinding(**wiring), KynoBinding(**wiring)}) == 1


def test_given_a_typed_detail_when_pulling_over_mcp_then_the_argument_is_a_plain_string():
    seen = {}

    class Session:
        async def call_tool(self, name, arguments):
            seen.update(arguments)
            payload = {
                "current_version": 0,
                "changed": False,
                "mission": "",
                "principles": [],
                "changed_mission": False,
                "changed_principles": False,
                "change_notes": [],
            }
            text = type("Text", (), {"text": json.dumps(payload)})()
            return type("Reply", (), {"content": [text]})()

    class Runner:
        def call(self, operation):
            return asyncio.run(operation(Session()))

    McpDirectionSource(Runner()).changes_since(0, "default", DetailLevel.FULL)

    assert seen["detail"] == "full"
    assert type(seen["detail"]) is str


def test_given_an_unknown_detail_when_pulling_over_mcp_then_it_is_refused_before_the_call():
    class Runner:
        def call(self, operation):
            raise AssertionError("MCP must not be called")

    with pytest.raises(ValueError, match="verbose"):
        McpDirectionSource(Runner()).changes_since(0, "default", "verbose")
