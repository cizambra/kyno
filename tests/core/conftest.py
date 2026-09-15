from functools import partial

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from kyno.mcp_server import build_server
from kyno.sdk import KynoConnection
from kyno.sdk.client import SessionRunner
from tests.workspaces import cli_workspace


@pytest.fixture
def cp(control_plane):
    return control_plane


@pytest.fixture
def mcp_runner(control_plane):
    server = build_server(control_plane)
    runner = SessionRunner(partial(create_connected_server_and_client_session, server))
    runner.start()
    try:
        yield runner, control_plane
    finally:
        runner.close()


@pytest.fixture
def mcp_connection(mcp_runner):
    runner, control_plane = mcp_runner
    return KynoConnection(runner), control_plane


@pytest.fixture
def remote_cli_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    cli_workspace(monkeypatch, tmp_path, tmp_path / "local.sqlite3", root=tmp_path / "work")
    return tmp_path
