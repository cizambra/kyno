"""The SDK's front door: kyno.connect() and the connection it returns."""

from contextlib import asynccontextmanager

import pytest

import kyno
from kyno.errors import KynoUnavailableError
from kyno.mcp_server import build_server
from kyno.sdk import KynoConnection, connect
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


def test_given_wiring_without_an_endpoint_when_connecting_then_it_is_refused(monkeypatch):
    monkeypatch.delenv("KYNO_URL", raising=False)
    with pytest.raises(KynoUnavailableError):
        connect()


def test_given_arguments_when_connecting_then_the_binding_is_built_from_them(monkeypatch):
    captured = {}

    def fake_http_session(binding):
        captured["binding"] = binding

        @asynccontextmanager
        async def factory(message_handler=None):
            yield object()

        return factory

    monkeypatch.setattr("kyno.sdk.http_session", fake_http_session)
    connection = connect("http://kyno.internal:8080/mcp/", token="t-1")
    try:
        assert captured["binding"].endpoint == "http://kyno.internal:8080/mcp/"
        assert captured["binding"].token == "t-1"
    finally:
        connection.close()


def test_given_no_arguments_when_connecting_then_the_environment_is_the_fallback(monkeypatch):
    captured = {}

    def fake_http_session(binding):
        captured["binding"] = binding

        @asynccontextmanager
        async def factory(message_handler=None):
            yield object()

        return factory

    monkeypatch.setattr("kyno.sdk.http_session", fake_http_session)
    monkeypatch.setenv("KYNO_URL", "http://from-env:8080/mcp/")
    monkeypatch.setenv("KYNO_TOKEN", "env-token")
    connection = connect()
    try:
        assert captured["binding"].endpoint == "http://from-env:8080/mcp/"
        assert captured["binding"].token == "env-token"
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


def test_given_the_sdk_when_looking_for_the_entry_point_then_it_is_kyno_connect():
    assert kyno.connect is connect
