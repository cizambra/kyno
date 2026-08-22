from contextlib import asynccontextmanager

import pytest

from kyno.errors import KynoUnavailableError
from kyno.mcp_server import build_server
from kyno.models import FULL
from kyno.sdk.binder import DirectionBinder
from kyno.sdk.client import (
    DirectionSource,
    KynoBinding,
    LocalDirectionSource,
    McpDirectionSource,
    SessionRunner,
    http_session,
)
from kyno.sdk.policy import PULL_FAILED_STALE, RecordingSink
from kyno.service import ControlPlane
from kyno.store.sql import SqlConstitutionStore


@pytest.fixture
def in_memory_runner():
    """The real MCP server over the SDK's in-memory transport: real protocol,
    real tool dispatch, no socket and no model."""
    store = SqlConstitutionStore(url="sqlite://")
    store.create_all()
    control_plane = ControlPlane(store)
    server = build_server(control_plane)

    @asynccontextmanager
    async def connect(message_handler=None):
        from mcp.shared.memory import create_connected_server_and_client_session

        async with create_connected_server_and_client_session(
            server, message_handler=message_handler
        ) as session:
            yield session

    runner = SessionRunner(connect)
    runner.start()
    try:
        yield runner, control_plane
    finally:
        runner.close()


def test_mcp_source_pulls_the_named_constitution(in_memory_runner):
    runner, control_plane = in_memory_runner
    control_plane.set_direction(mission="EU mission", change_note="init", constitution="eu")
    control_plane.set_direction(mission="US mission", change_note="init", constitution="us")
    source = McpDirectionSource(runner)

    assert source.changes_since(0, "eu").mission == "EU mission"
    assert source.changes_since(0, "us").mission == "US mission"


def test_mcp_source_reports_change_notes_since_the_known_version(in_memory_runner):
    runner, control_plane = in_memory_runner
    control_plane.set_direction(mission="M1", change_note="init")
    control_plane.set_direction(mission="M2", change_note="pivot")
    source = McpDirectionSource(runner)

    changes = source.changes_since(1, "default")

    assert changes.current_version == 2 and changes.changed is True
    assert changes.change_notes == ("pivot",)


def test_mcp_source_reads_an_unwritten_name_as_version_zero(in_memory_runner):
    runner, _cp = in_memory_runner
    assert McpDirectionSource(runner).changes_since(0, "never-written").current_version == 0


def test_a_binder_over_mcp_binds_each_step_to_the_live_version(in_memory_runner):
    runner, control_plane = in_memory_runner
    control_plane.set_direction(mission="M1", change_note="init", constitution="eu")
    binder = DirectionBinder(McpDirectionSource(runner))

    first = binder.bind("eu")
    control_plane.set_direction(mission="M2", change_note="pivot", constitution="eu")
    second = binder.bind("eu")

    assert (first.version, second.version) == (1, 2)
    assert second.mission == "M2"


def test_a_closed_runner_raises_unavailable_not_hangs(in_memory_runner):
    runner, _cp = in_memory_runner
    runner.close()

    with pytest.raises(KynoUnavailableError):
        McpDirectionSource(runner).changes_since(0, "default")


def test_mcp_source_satisfies_the_protocol(in_memory_runner):
    runner, _cp = in_memory_runner
    assert isinstance(McpDirectionSource(runner), DirectionSource)


def test_the_two_sources_answer_the_same_question_the_same_way(in_memory_runner):
    """The in-process and MCP paths must stay interchangeable for a binder."""
    runner, control_plane = in_memory_runner
    control_plane.set_direction(mission="M1", change_note="init", constitution="eu")
    control_plane.set_direction(principles=("Be honest",), change_note="add", constitution="eu")

    over_mcp = McpDirectionSource(runner).changes_since(1, "eu")
    in_process = LocalDirectionSource(control_plane).changes_since(1, "eu")

    assert over_mcp == in_process


def test_a_crew_keeps_running_on_the_last_direction_when_kyno_goes_away(in_memory_runner):
    runner, control_plane = in_memory_runner
    control_plane.set_direction(mission="M1", change_note="init")
    sink = RecordingSink()
    binder = DirectionBinder(McpDirectionSource(runner), telemetry=sink)
    binder.bind()

    runner.close()
    direction = binder.bind()

    assert direction.version == 1 and direction.mission == "M1"
    assert [e.kind for e in sink.events] == [PULL_FAILED_STALE]


def test_a_message_handler_must_be_set_before_the_session_opens(in_memory_runner):
    """The handler is handed to the session once, at open time."""
    runner, _cp = in_memory_runner
    with pytest.raises(RuntimeError):
        runner.set_message_handler(lambda message: None)


def test_a_runner_that_cannot_connect_fails_loudly_at_start():
    @asynccontextmanager
    async def connect(message_handler=None):
        raise OSError("connection refused")
        yield  # pragma: no cover - unreachable, keeps this a generator

    with pytest.raises(KynoUnavailableError):
        SessionRunner(connect).start()


def test_closing_a_runner_twice_is_harmless(in_memory_runner):
    runner, _cp = in_memory_runner
    runner.close()
    runner.close()


def test_http_session_needs_an_endpoint():
    with pytest.raises(KynoUnavailableError):
        http_session(KynoBinding(constitution="eu"))


async def test_http_session_sends_the_token_as_a_bearer_header(monkeypatch):
    captured = _fake_transport(monkeypatch)

    connect = http_session(KynoBinding(endpoint="https://kyno.internal/mcp", token="secret"))
    async with connect():
        pass

    assert captured["url"] == "https://kyno.internal/mcp"
    assert captured["headers"] == {"Authorization": "Bearer secret"}
    assert captured["initialized"] is True


async def test_http_session_without_a_token_sends_no_auth_header(monkeypatch):
    captured = _fake_transport(monkeypatch)

    connect = http_session(KynoBinding(endpoint="https://kyno.internal/mcp"))
    async with connect(message_handler="handler"):
        pass

    assert captured["headers"] is None
    assert captured["message_handler"] == "handler"


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


def test_a_full_binding_pulls_the_declaration_and_the_descriptions(in_memory_runner):
    runner, control_plane = in_memory_runner
    control_plane.set_direction(
        mission="M1",
        declaration="The long form.",
        principles=({"title": "Be honest", "description": "Say the hard number first."},),
        change_note="init",
    )
    source = McpDirectionSource(runner)

    compact = source.changes_since(0, "default")
    full = source.changes_since(0, "default", FULL)

    assert compact.declaration == ""
    assert compact.principles[0].description == ""
    assert full.declaration == "The long form."
    assert full.principles[0].description == "Say the hard number first."
