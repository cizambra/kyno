"""MCP direction-source behavior over the in-memory server."""

from contextlib import asynccontextmanager

import pytest

from kyno.mcp_server import build_server
from kyno.sdk.binder import DirectionBinder
from kyno.sdk.client import DirectionSource, LocalDirectionSource, McpDirectionSource, SessionRunner
from kyno.sdk.errors import KynoUnavailableError
from kyno.sdk.telemetry import EventType, RecordingSink
from kyno.service import ControlPlane
from kyno.store.sql import SqlConstitutionStore
from kyno.wire.models import DetailLevel


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


def test_given_a_name_when_the_mcp_source_pulls_then_that_constitution_comes(in_memory_runner):
    runner, control_plane = in_memory_runner
    control_plane.set_direction(mission="EU mission", change_note="init", constitution="eu")
    control_plane.set_direction(mission="US mission", change_note="init", constitution="us")
    source = McpDirectionSource(runner)

    assert source.changes_since(0, "eu").mission == "EU mission"
    assert source.changes_since(0, "us").mission == "US mission"


def test_given_a_known_version_when_the_mcp_source_reports_then_the_notes_since_come(
    in_memory_runner,
):
    runner, control_plane = in_memory_runner
    control_plane.set_direction(mission="M1", change_note="init")
    control_plane.set_direction(mission="M2", change_note="pivot")
    source = McpDirectionSource(runner)

    changes = source.changes_since(1, "default")

    assert changes.current_version == 2 and changes.changed is True
    assert changes.change_notes == ("pivot",)


def test_given_an_unwritten_name_when_the_mcp_source_reads_then_it_is_version_zero(
    in_memory_runner,
):
    runner, _cp = in_memory_runner
    assert McpDirectionSource(runner).changes_since(0, "never-written").current_version == 0


def test_given_a_binder_over_mcp_when_steps_run_then_each_binds_the_live_version(in_memory_runner):
    runner, control_plane = in_memory_runner
    control_plane.set_direction(mission="M1", change_note="init", constitution="eu")
    binder = DirectionBinder(McpDirectionSource(runner))

    first = binder.bind("eu")
    control_plane.set_direction(mission="M2", change_note="pivot", constitution="eu")
    second = binder.bind("eu")

    assert (first.version, second.version) == (1, 2)
    assert second.mission == "M2"


def test_given_a_closed_runner_when_pulling_then_unavailable_raises_instead_of_hanging(
    in_memory_runner,
):
    runner, _cp = in_memory_runner
    runner.close()

    with pytest.raises(KynoUnavailableError):
        McpDirectionSource(runner).changes_since(0, "default")


def test_given_the_mcp_source_when_checking_the_protocol_then_it_satisfies_it(in_memory_runner):
    runner, _cp = in_memory_runner
    assert isinstance(McpDirectionSource(runner), DirectionSource)


def test_given_the_two_sources_when_asking_the_same_question_then_the_answers_match(
    in_memory_runner,
):
    """The in-process and MCP paths must stay interchangeable for a binder."""
    runner, control_plane = in_memory_runner
    control_plane.set_direction(mission="M1", change_note="init", constitution="eu")
    control_plane.set_direction(principles=("Be honest",), change_note="add", constitution="eu")

    over_mcp = McpDirectionSource(runner).changes_since(1, "eu")
    in_process = LocalDirectionSource(control_plane).changes_since(1, "eu")

    assert over_mcp == in_process


def test_given_kyno_going_away_when_a_crew_is_running_then_the_last_direction_carries_it(
    in_memory_runner,
):
    runner, control_plane = in_memory_runner
    control_plane.set_direction(mission="M1", change_note="init")
    sink = RecordingSink()
    binder = DirectionBinder(McpDirectionSource(runner), telemetry=sink)
    binder.bind()

    runner.close()
    direction = binder.bind()

    assert direction.version == 1 and direction.mission == "M1"
    assert [event.kind for event in sink.events] == [EventType.PULL_FAILED_STALE]


def test_given_no_message_handler_when_the_session_opens_then_it_is_refused(in_memory_runner):
    """The handler is handed to the session once, at open time."""
    runner, _cp = in_memory_runner
    with pytest.raises(RuntimeError):
        runner.set_message_handler(lambda message: None)


def test_given_a_closed_runner_when_closing_again_then_it_is_harmless(in_memory_runner):
    runner, _cp = in_memory_runner
    runner.close()
    runner.close()


def test_given_a_full_binding_when_pulling_then_the_declaration_and_descriptions_come(
    in_memory_runner,
):
    runner, control_plane = in_memory_runner
    control_plane.set_direction(
        mission="M1",
        declaration="The long form.",
        principles=({"title": "Be honest", "description": "Say the hard number first."},),
        change_note="init",
    )
    source = McpDirectionSource(runner)

    compact = source.changes_since(0, "default")
    full = source.changes_since(0, "default", DetailLevel.FULL)

    assert compact.declaration == ""
    assert compact.principles[0].description == ""
    assert full.declaration == "The long form."
    assert full.principles[0].description == "Say the hard number first."
