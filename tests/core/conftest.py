import pytest

from tests.workspaces import cli_workspace


@pytest.fixture
def cp(control_plane):
    return control_plane


@pytest.fixture
def remote_cli_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    cli_workspace(monkeypatch, tmp_path, tmp_path / "local.sqlite3", root=tmp_path / "work")
    return tmp_path
