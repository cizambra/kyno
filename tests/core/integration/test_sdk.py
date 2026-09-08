"""The SDK connection over the real MCP server."""

from contextlib import asynccontextmanager

import pytest

from kyno.mcp_server import build_server
from kyno.sdk import KynoConnection
from kyno.sdk.client import SessionRunner
from kyno.service import ControlPlane
from kyno.store.sql import SqlConstitutionStore


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


def test_given_a_closed_connection_when_binding_then_it_degrades_instead_of_crashing(
    in_memory_connection,
):
    connection, control_plane = in_memory_connection
    binder = connection.binder()
    connection.close()

    direction = binder.bind()
    assert direction.version == 0
