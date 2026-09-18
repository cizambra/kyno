"""CLI selectors preserve omission until Core resolves the target constitution."""

import json
from unittest.mock import Mock

import pytest

import kyno.cli as cli
from kyno.service import ControlPlane
from tests.remote_cli import runner


@pytest.mark.parametrize(
    ("command", "operation"),
    [
        (["current"], "current"),
        (["get-version", "1"], "export_versions"),
        (["history"], "export_versions"),
        (["export"], "export_versions"),
        (["publish"], "publish"),
        (["unpublish"], "unpublish"),
    ],
)
def test_given_no_cli_key_when_running_direction_command_then_core_receives_none(
    monkeypatch, memory_store, command, operation
):
    plane = ControlPlane(memory_store)
    plane.apply_direction(mission="Default direction", change_note="Initial")
    observed = Mock(wraps=plane)
    monkeypatch.setattr(cli, "_control_plane", lambda: observed)
    monkeypatch.setattr(cli, "_store", lambda: memory_store)

    result = runner.invoke(cli.app, command)

    assert result.exit_code == 0, result.output
    assert getattr(observed, operation).call_args.args[0] is None


@pytest.mark.parametrize("command", [["current"], ["get-version", "1"], ["history"], ["export"]])
def test_given_no_remote_cli_key_when_reading_direction_then_mcp_arguments_omit_the_key(
    monkeypatch, memory_store, command
):
    plane = ControlPlane(memory_store)
    version = plane.apply_direction(mission="Default direction", change_note="Initial")
    remote = Mock()
    remote.call_tool.return_value = (
        version.to_dict() if command == ["current"] else plane.export_versions()
    )
    monkeypatch.setattr(cli, "dial", lambda *args, **kwargs: remote)

    result = runner.invoke(cli.app, [*command, "--remote"])

    assert result.exit_code == 0, result.output
    assert "constitution_key" not in remote.call_tool.call_args.args[1]
    remote.close.assert_called_once()


def test_given_no_import_destination_when_importing_then_core_resolves_the_target(
    monkeypatch, memory_store, tmp_path
):
    plane = ControlPlane(memory_store)
    plane.apply_direction(
        mission="Support direction", change_note="Initial", constitution_key="support"
    )
    backup = tmp_path / "backup.json"
    backup.write_text(json.dumps(plane.export_versions("support")))
    observed = Mock(wraps=plane)
    monkeypatch.setattr(cli, "_control_plane", lambda: observed)
    monkeypatch.setattr(cli, "_store", lambda: memory_store)

    result = runner.invoke(cli.app, ["import", str(backup)])

    assert result.exit_code == 0, result.output
    observed.current.assert_called_once_with(None)
    assert plane.current().mission == "Support direction"


@pytest.mark.parametrize("remote", [False, True])
def test_given_padded_explicit_key_when_reading_current_then_only_that_normalized_key_is_requested(
    monkeypatch, memory_store, remote
):
    plane = ControlPlane(memory_store)
    version = plane.apply_direction(
        mission="Support direction", change_note="Initial", constitution_key="support"
    )
    observed = Mock(wraps=plane)
    client = Mock()
    client.call_tool.return_value = version.to_dict()
    monkeypatch.setattr(cli, "_control_plane", lambda: observed)
    monkeypatch.setattr(cli, "dial", lambda *args, **kwargs: client)
    arguments = ["current", "--constitution-key", " support "]
    if remote:
        arguments.append("--remote")

    result = runner.invoke(cli.app, arguments)

    assert result.exit_code == 0, result.output
    if remote:
        assert client.call_tool.call_args.args[1]["constitution_key"] == "support"
    else:
        observed.current.assert_called_once_with("support")


@pytest.mark.parametrize("key", ["", " ", "Support", "support/team"])
@pytest.mark.parametrize("remote", [False, True])
def test_given_invalid_explicit_key_when_reading_current_then_no_local_or_remote_read_runs(
    monkeypatch, key, remote
):
    local = Mock()
    dial = Mock()
    monkeypatch.setattr(cli, "_control_plane", local)
    monkeypatch.setattr(cli, "dial", dial)
    arguments = ["current", "--constitution-key", key]
    if remote:
        arguments.append("--remote")

    result = runner.invoke(cli.app, arguments)

    assert result.exit_code != 0
    assert "constitution key" in result.output
    local.assert_not_called()
    dial.assert_not_called()
