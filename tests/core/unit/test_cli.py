from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

from kyno import cli


@pytest.mark.parametrize(
    "arguments",
    [
        ["get-version", "latest"],
        ["get-version", "latest", "--remote"],
        ["publish"],
        ["unpublish"],
        ["history"],
        ["history", "--remote"],
        ["export"],
        ["export", "--remote"],
    ],
)
@pytest.mark.parametrize("key", ["Upper", "bad/name", "a" * 201])
def test_given_invalid_key_when_cli_command_runs_then_clean_error_precedes_dependencies(
    monkeypatch, arguments, key
):
    dependencies = Mock(side_effect=AssertionError("dependency called"))
    for name in ("_control_plane", "_store", "_read_direction_version", "_fetch_remote_rows"):
        monkeypatch.setattr(cli, name, dependencies)

    result = CliRunner().invoke(cli.app, [*arguments, "--constitution", key])

    assert result.exit_code == 1
    assert "error:" in result.stderr
    assert "constitution key" in result.stderr
    assert "Traceback" not in result.output
    dependencies.assert_not_called()


@pytest.mark.parametrize("key", ["Upper", "a" * 201])
def test_given_invalid_import_key_when_cli_import_runs_then_clean_error_precedes_file_and_store(
    monkeypatch,
    key,
):
    dependencies = Mock(side_effect=AssertionError("dependency called"))
    monkeypatch.setattr(cli, "_store", dependencies)
    monkeypatch.setattr(cli, "_read_export", dependencies)

    result = CliRunner().invoke(cli.app, ["import", "ledger.json", "--as", key])

    assert result.exit_code == 1
    assert "error:" in result.stderr
    assert "constitution key" in result.stderr
    assert "Traceback" not in result.output
    dependencies.assert_not_called()
