"""The SDK connection over the real MCP server."""

from contextlib import asynccontextmanager

import pytest

from kyno.mcp_server import build_server
from kyno.sdk import DirectionCell, KynoConnection
from kyno.sdk.client import SessionRunner
from kyno.service import ControlPlane
from kyno.store.sql import SqlConstitutionStore
from kyno.wire.models import DetailLevel


@pytest.fixture
def in_memory_connection():
    """A connection over the real MCP server on the in-memory transport."""
    store = SqlConstitutionStore(url="sqlite://")
    store.create_all()
    control_plane = ControlPlane(store)
    server = build_server(control_plane)

    @asynccontextmanager
    async def session_factory(message_handler=None):
        from mcp.shared.memory import create_connected_server_and_client_session

        async with create_connected_server_and_client_session(
            server, message_handler=message_handler
        ) as session:
            yield session

    runner = SessionRunner(session_factory)
    runner.start()
    connection = KynoConnection(runner)
    try:
        yield connection, control_plane
    finally:
        connection.close()


def test_given_a_connection_when_its_binder_binds_then_the_direction_in_force_serves(
    in_memory_connection,
):
    connection, control_plane = in_memory_connection
    control_plane.set_direction(mission="M1", change_note="init")
    binder = connection.binder()

    assert "version=1" in binder.bind().render()

    control_plane.set_direction(mission="M2", change_note="pivot")
    assert "version=2" in binder.bind().render()


def test_given_one_connection_when_making_binders_then_they_share_the_session(in_memory_connection):
    connection, control_plane = in_memory_connection
    control_plane.set_direction(mission="M1", change_note="init")

    first = connection.binder()
    second = connection.binder()
    assert first.bind().version == 1
    assert second.bind().version == 1

    connection.close()
    # Both degrade together because there is one session under them; the
    # last-known direction keeps serving.
    assert first.bind().version == 1
    assert second.bind().version == 1


@pytest.mark.parametrize("first_context", list(DetailLevel))
def test_given_a_shared_cell_when_connection_requests_another_context_then_setup_is_rejected(
    in_memory_connection, first_context
):
    connection, _control_plane = in_memory_connection
    cell = DirectionCell()
    connection.binder(cell=cell, context=first_context)
    other_context = (
        DetailLevel.FULL if first_context is DetailLevel.COMPACT else DetailLevel.COMPACT
    )

    with pytest.raises(ValueError, match="separate cell"):
        connection.binder(cell=cell, context=other_context)

    assert cell.names() == ()


def test_given_one_connection_when_contexts_use_separate_cells_then_both_read_requested_direction(
    in_memory_connection,
):
    connection, control_plane = in_memory_connection
    control_plane.set_direction(
        mission="Help customers", declaration="Explain each decision", change_note="init"
    )
    compact_cell = DirectionCell()
    full_cell = DirectionCell()
    compact = connection.binder(cell=compact_cell, context=DetailLevel.COMPACT).bind()
    full = connection.binder(cell=full_cell, context=DetailLevel.FULL).bind()

    assert compact.context is DetailLevel.COMPACT
    assert full.context is DetailLevel.FULL
    assert compact.version == full.version == 1
    assert compact_cell.get("default") is compact
    assert full_cell.get("default") is full
    assert "Explain each decision" not in compact.render()
    assert "Explain each decision" in full.render()


def test_given_a_closed_connection_when_binding_then_it_degrades_instead_of_crashing(
    in_memory_connection,
):
    connection, control_plane = in_memory_connection
    binder = connection.binder()
    connection.close()

    direction = binder.bind()
    assert direction.version == 0
