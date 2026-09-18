"""CLI selectors preserve omission until Core resolves the target constitution."""

import json
from unittest.mock import Mock

import pytest
import yaml

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


@pytest.mark.parametrize(
    "command", [["current"], ["current", "--yaml"], ["get-version", "1"], ["export"]]
)
@pytest.mark.parametrize(
    "identity",
    [
        {},
        {"constitution_key": None},
        {"constitution_key": ""},
        {"constitution_key": "Upper"},
        {"constitution_key": []},
    ],
)
def test_given_invalid_remote_identity_when_reading_direction_then_error_is_clean(
    monkeypatch, command, identity
):
    remote = Mock()
    payload = {"version": 0 if command[0] == "current" else 1, **identity}
    remote.call_tool.return_value = payload if command[0] == "current" else [payload]
    monkeypatch.setattr(cli, "dial", lambda *args, **kwargs: remote)

    result = runner.invoke(cli.app, [*command, "--remote"])

    assert result.exit_code == 1
    assert isinstance(result.exception, SystemExit)
    assert result.stdout == ""
    assert "constitution key" in result.stderr
    remote.close.assert_called_once()


@pytest.mark.parametrize(
    "command", [["current", "--yaml"], ["get-version", "1", "--yaml"], ["export"]]
)
def test_given_server_selected_key_when_cli_omits_selector_then_output_names_returned_key(
    monkeypatch, memory_store, command
):
    plane = ControlPlane(memory_store)
    version = plane.apply_direction(
        constitution_key="server-selected", mission="Server direction", change_note="Initial"
    )
    remote = Mock()
    remote.call_tool.return_value = (
        version.to_dict() if command[0] == "current" else plane.export_versions("server-selected")
    )
    monkeypatch.setattr(cli, "dial", lambda *args, **kwargs: remote)

    result = runner.invoke(cli.app, [*command, "--remote"])

    assert result.exit_code == 0, result.output
    assert "constitution_key" not in remote.call_tool.call_args.args[1]
    if command[0] == "export":
        assert "Constitution 'server-selected' exported" in result.stderr
        assert json.loads(result.stdout)[0]["constitution_key"] == "server-selected"
    else:
        assert yaml.safe_load(result.stdout)["constitution_key"] == "server-selected"


@pytest.mark.parametrize("command", ["publish", "unpublish"])
def test_given_core_publication_identity_when_cli_omits_selector_then_output_names_returned_key(
    monkeypatch, command
):
    plane = Mock()
    getattr(plane, command).return_value.constitution_key = "core-selected"
    getattr(plane, command).return_value.history_public = False
    monkeypatch.setattr(cli, "_control_plane", lambda: plane)

    result = runner.invoke(cli.app, [command])

    assert result.exit_code == 0, result.output
    assert "'core-selected'" in result.stdout
    assert getattr(plane, command).call_args.args[0] is None


def test_given_unwritten_server_target_when_cli_requests_yaml_then_error_names_returned_key(
    monkeypatch,
):
    remote = Mock()
    remote.call_tool.return_value = {"version": 0, "constitution_key": "server-selected"}
    monkeypatch.setattr(cli, "dial", lambda *args, **kwargs: remote)

    result = runner.invoke(cli.app, ["current", "--remote", "--yaml"])

    assert result.exit_code == 1
    assert isinstance(result.exception, SystemExit)
    assert result.stdout == ""
    assert "'server-selected' has no versions" in result.stderr
