"""CLI selectors preserve omission until Core resolves the target constitution."""

import json
from unittest.mock import Mock

import pytest
import yaml

import kyno.cli as cli
from kyno.service import ControlPlane
from tests.remote_cli import runner


def test_given_mismatched_key_when_cli_current_runs_then_error_prevents_output(
    monkeypatch, memory_store
):
    plane = ControlPlane(memory_store)
    version = plane.apply_direction(
        constitution_key="sales", mission="Grow sales", change_note="Initial"
    )
    remote = Mock()
    remote.call_tool.return_value = version.to_dict()
    monkeypatch.setattr(cli, "dial", lambda *args, **kwargs: remote)

    result = runner.invoke(cli.app, ["current", "--remote", "--constitution-key", " support "])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "constitution key" in result.stderr
    assert "sales" in result.stderr
    assert "support" in result.stderr
    assert remote.call_tool.call_args.args[1]["constitution_key"] == "support"
    remote.close.assert_called_once()


def test_given_mismatched_key_when_cli_current_yaml_runs_then_error_prevents_output(
    monkeypatch, memory_store
):
    plane = ControlPlane(memory_store)
    version = plane.apply_direction(
        constitution_key="sales", mission="Grow sales", change_note="Initial"
    )
    remote = Mock()
    remote.call_tool.return_value = version.to_dict()
    monkeypatch.setattr(cli, "dial", lambda *args, **kwargs: remote)

    result = runner.invoke(
        cli.app, ["current", "--yaml", "--remote", "--constitution-key", " support "]
    )

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "constitution key" in result.stderr
    assert "sales" in result.stderr
    assert "support" in result.stderr
    assert remote.call_tool.call_args.args[1]["constitution_key"] == "support"
    remote.close.assert_called_once()


def test_given_mismatched_key_when_cli_get_version_number_runs_then_error_prevents_output(
    monkeypatch, memory_store
):
    plane = ControlPlane(memory_store)
    version = plane.apply_direction(
        constitution_key="sales", mission="Grow sales", change_note="Initial"
    )
    remote = Mock()
    remote.call_tool.return_value = [version.to_dict()]
    monkeypatch.setattr(cli, "dial", lambda *args, **kwargs: remote)

    result = runner.invoke(
        cli.app, ["get-version", "1", "--remote", "--constitution-key", " support "]
    )

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "constitution key" in result.stderr
    assert "sales" in result.stderr
    assert "support" in result.stderr
    assert remote.call_tool.call_args.args[1]["constitution_key"] == "support"
    remote.close.assert_called_once()


def test_given_mismatched_key_when_cli_get_version_number_yaml_runs_then_error_prevents_output(
    monkeypatch, memory_store
):
    plane = ControlPlane(memory_store)
    version = plane.apply_direction(
        constitution_key="sales", mission="Grow sales", change_note="Initial"
    )
    remote = Mock()
    remote.call_tool.return_value = [version.to_dict()]
    monkeypatch.setattr(cli, "dial", lambda *args, **kwargs: remote)

    result = runner.invoke(
        cli.app, ["get-version", "1", "--yaml", "--remote", "--constitution-key", " support "]
    )

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "constitution key" in result.stderr
    assert "sales" in result.stderr
    assert "support" in result.stderr
    assert remote.call_tool.call_args.args[1]["constitution_key"] == "support"
    remote.close.assert_called_once()


def test_given_mismatched_key_when_cli_history_runs_then_error_prevents_output(
    monkeypatch, memory_store
):
    plane = ControlPlane(memory_store)
    version = plane.apply_direction(
        constitution_key="sales", mission="Grow sales", change_note="Initial"
    )
    remote = Mock()
    remote.call_tool.return_value = [version.to_dict()]
    monkeypatch.setattr(cli, "dial", lambda *args, **kwargs: remote)

    result = runner.invoke(cli.app, ["history", "--remote", "--constitution-key", " support "])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "constitution key" in result.stderr
    assert "sales" in result.stderr
    assert "support" in result.stderr
    assert remote.call_tool.call_args.args[1]["constitution_key"] == "support"
    remote.close.assert_called_once()


def test_given_mismatched_key_when_cli_export_runs_then_error_prevents_output(
    monkeypatch, memory_store
):
    plane = ControlPlane(memory_store)
    version = plane.apply_direction(
        constitution_key="sales", mission="Grow sales", change_note="Initial"
    )
    remote = Mock()
    remote.call_tool.return_value = [version.to_dict()]
    monkeypatch.setattr(cli, "dial", lambda *args, **kwargs: remote)

    result = runner.invoke(cli.app, ["export", "--remote", "--constitution-key", " support "])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "constitution key" in result.stderr
    assert "sales" in result.stderr
    assert "support" in result.stderr
    assert remote.call_tool.call_args.args[1]["constitution_key"] == "support"
    remote.close.assert_called_once()


@pytest.mark.parametrize("explicit", [False, True])
def test_given_mixed_keys_when_cli_history_runs_then_error_prevents_output(
    monkeypatch, memory_store, explicit
):
    plane = ControlPlane(memory_store)
    support = plane.apply_direction(
        constitution_key="support", mission="Help", change_note="Initial"
    )
    sales = plane.apply_direction(constitution_key="sales", mission="Sell", change_note="Initial")
    remote = Mock()
    remote.call_tool.return_value = [support.to_dict(), sales.to_dict()]
    monkeypatch.setattr(cli, "dial", lambda *args, **kwargs: remote)
    arguments = ["history", "--remote"]
    if explicit:
        arguments.extend(["--constitution-key", "support"])

    result = runner.invoke(cli.app, arguments)

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "constitution key" in result.stderr
    remote.close.assert_called_once()


@pytest.mark.parametrize("explicit", [False, True])
def test_given_mixed_keys_when_cli_export_runs_then_error_prevents_output(
    monkeypatch, memory_store, explicit
):
    plane = ControlPlane(memory_store)
    support = plane.apply_direction(
        constitution_key="support", mission="Help", change_note="Initial"
    )
    sales = plane.apply_direction(constitution_key="sales", mission="Sell", change_note="Initial")
    remote = Mock()
    remote.call_tool.return_value = [support.to_dict(), sales.to_dict()]
    monkeypatch.setattr(cli, "dial", lambda *args, **kwargs: remote)
    arguments = ["export", "--remote"]
    if explicit:
        arguments.extend(["--constitution-key", "support"])

    result = runner.invoke(cli.app, arguments)

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "constitution key" in result.stderr
    remote.close.assert_called_once()


def test_given_no_constitution_key_when_cli_current_runs_then_core_receives_none(
    monkeypatch, memory_store
):
    plane = ControlPlane(memory_store)
    plane.apply_direction(mission="Default direction", change_note="Initial")
    observed = Mock(wraps=plane)
    monkeypatch.setattr(cli, "_control_plane", lambda: observed)
    monkeypatch.setattr(cli, "_store", lambda: memory_store)

    result = runner.invoke(cli.app, ["current"])

    assert result.exit_code == 0, result.output
    assert observed.current.call_args.args[0] is None


def test_given_no_constitution_key_when_cli_get_version_runs_then_core_receives_none(
    monkeypatch, memory_store
):
    plane = ControlPlane(memory_store)
    plane.apply_direction(mission="Default direction", change_note="Initial")
    observed = Mock(wraps=plane)
    monkeypatch.setattr(cli, "_control_plane", lambda: observed)
    monkeypatch.setattr(cli, "_store", lambda: memory_store)

    result = runner.invoke(cli.app, ["get-version", "1"])

    assert result.exit_code == 0, result.output
    assert observed.export_versions.call_args.args[0] is None


def test_given_no_constitution_key_when_cli_history_runs_then_core_receives_none(
    monkeypatch, memory_store
):
    plane = ControlPlane(memory_store)
    plane.apply_direction(mission="Default direction", change_note="Initial")
    observed = Mock(wraps=plane)
    monkeypatch.setattr(cli, "_control_plane", lambda: observed)
    monkeypatch.setattr(cli, "_store", lambda: memory_store)

    result = runner.invoke(cli.app, ["history"])

    assert result.exit_code == 0, result.output
    assert observed.export_versions.call_args.args[0] is None


def test_given_no_constitution_key_when_cli_export_runs_then_core_receives_none(
    monkeypatch, memory_store
):
    plane = ControlPlane(memory_store)
    plane.apply_direction(mission="Default direction", change_note="Initial")
    observed = Mock(wraps=plane)
    monkeypatch.setattr(cli, "_control_plane", lambda: observed)
    monkeypatch.setattr(cli, "_store", lambda: memory_store)

    result = runner.invoke(cli.app, ["export"])

    assert result.exit_code == 0, result.output
    assert observed.export_versions.call_args.args[0] is None


def test_given_no_constitution_key_when_cli_publish_runs_then_core_receives_none(
    monkeypatch, memory_store
):
    plane = ControlPlane(memory_store)
    plane.apply_direction(mission="Default direction", change_note="Initial")
    observed = Mock(wraps=plane)
    monkeypatch.setattr(cli, "_control_plane", lambda: observed)
    monkeypatch.setattr(cli, "_store", lambda: memory_store)

    result = runner.invoke(cli.app, ["publish"])

    assert result.exit_code == 0, result.output
    assert observed.publish.call_args.args[0] is None


def test_given_no_constitution_key_when_cli_unpublish_runs_then_core_receives_none(
    monkeypatch, memory_store
):
    plane = ControlPlane(memory_store)
    plane.apply_direction(mission="Default direction", change_note="Initial")
    observed = Mock(wraps=plane)
    monkeypatch.setattr(cli, "_control_plane", lambda: observed)
    monkeypatch.setattr(cli, "_store", lambda: memory_store)

    result = runner.invoke(cli.app, ["unpublish"])

    assert result.exit_code == 0, result.output
    assert observed.unpublish.call_args.args[0] is None


def test_given_no_constitution_key_when_cli_current_runs_then_mcp_arguments_omit_the_key(
    monkeypatch, memory_store
):
    plane = ControlPlane(memory_store)
    version = plane.apply_direction(mission="Default direction", change_note="Initial")
    remote = Mock()
    remote.call_tool.return_value = version.to_dict()
    monkeypatch.setattr(cli, "dial", lambda *args, **kwargs: remote)

    result = runner.invoke(cli.app, ["current", "--remote"])

    assert result.exit_code == 0, result.output
    assert "constitution_key" not in remote.call_tool.call_args.args[1]
    remote.close.assert_called_once()


def test_given_no_constitution_key_when_cli_get_version_runs_then_mcp_omits_the_key(
    monkeypatch, memory_store
):
    plane = ControlPlane(memory_store)
    plane.apply_direction(mission="Default direction", change_note="Initial")
    remote = Mock()
    remote.call_tool.return_value = plane.export_versions()
    monkeypatch.setattr(cli, "dial", lambda *args, **kwargs: remote)

    result = runner.invoke(cli.app, ["get-version", "1", "--remote"])

    assert result.exit_code == 0, result.output
    assert "constitution_key" not in remote.call_tool.call_args.args[1]
    remote.close.assert_called_once()


def test_given_no_constitution_key_when_cli_history_runs_then_mcp_arguments_omit_the_key(
    monkeypatch, memory_store
):
    plane = ControlPlane(memory_store)
    plane.apply_direction(mission="Default direction", change_note="Initial")
    remote = Mock()
    remote.call_tool.return_value = plane.export_versions()
    monkeypatch.setattr(cli, "dial", lambda *args, **kwargs: remote)

    result = runner.invoke(cli.app, ["history", "--remote"])

    assert result.exit_code == 0, result.output
    assert "constitution_key" not in remote.call_tool.call_args.args[1]
    remote.close.assert_called_once()


def test_given_no_constitution_key_when_cli_export_runs_then_mcp_arguments_omit_the_key(
    monkeypatch, memory_store
):
    plane = ControlPlane(memory_store)
    plane.apply_direction(mission="Default direction", change_note="Initial")
    remote = Mock()
    remote.call_tool.return_value = plane.export_versions()
    monkeypatch.setattr(cli, "dial", lambda *args, **kwargs: remote)

    result = runner.invoke(cli.app, ["export", "--remote"])

    assert result.exit_code == 0, result.output
    assert "constitution_key" not in remote.call_tool.call_args.args[1]
    remote.close.assert_called_once()


def test_given_omitted_destination_when_cli_import_then_core_resolves_target(
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
def test_given_padded_explicit_key_when_cli_current_then_only_that_normalized_key_is_requested(
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
def test_given_invalid_explicit_key_when_cli_current_then_no_local_or_remote_read_runs(
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
    "identity",
    [
        {},
        {"constitution_key": None},
        {"constitution_key": ""},
        {"constitution_key": "Upper"},
        {"constitution_key": []},
    ],
)
def test_given_invalid_remote_identity_when_cli_current_runs_then_error_is_clean(
    monkeypatch, identity
):
    remote = Mock()
    payload = {"version": 0, **identity}
    remote.call_tool.return_value = payload
    monkeypatch.setattr(cli, "dial", lambda *args, **kwargs: remote)

    result = runner.invoke(cli.app, ["current", "--remote"])

    assert result.exit_code == 1
    assert isinstance(result.exception, SystemExit)
    assert result.stdout == ""
    assert "constitution key" in result.stderr
    remote.close.assert_called_once()


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
def test_given_invalid_remote_identity_when_cli_current_yaml_runs_then_error_is_clean(
    monkeypatch, identity
):
    remote = Mock()
    payload = {"version": 0, **identity}
    remote.call_tool.return_value = payload
    monkeypatch.setattr(cli, "dial", lambda *args, **kwargs: remote)

    result = runner.invoke(cli.app, ["current", "--yaml", "--remote"])

    assert result.exit_code == 1
    assert isinstance(result.exception, SystemExit)
    assert result.stdout == ""
    assert "constitution key" in result.stderr
    remote.close.assert_called_once()


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
def test_given_invalid_remote_identity_when_cli_get_version_number_runs_then_error_is_clean(
    monkeypatch, identity
):
    remote = Mock()
    payload = {"version": 1, **identity}
    remote.call_tool.return_value = [payload]
    monkeypatch.setattr(cli, "dial", lambda *args, **kwargs: remote)

    result = runner.invoke(cli.app, ["get-version", "1", "--remote"])

    assert result.exit_code == 1
    assert isinstance(result.exception, SystemExit)
    assert result.stdout == ""
    assert "constitution key" in result.stderr
    remote.close.assert_called_once()


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
def test_given_invalid_remote_identity_when_cli_export_runs_then_error_is_clean(
    monkeypatch, identity
):
    remote = Mock()
    payload = {"version": 1, **identity}
    remote.call_tool.return_value = [payload]
    monkeypatch.setattr(cli, "dial", lambda *args, **kwargs: remote)

    result = runner.invoke(cli.app, ["export", "--remote"])

    assert result.exit_code == 1
    assert isinstance(result.exception, SystemExit)
    assert result.stdout == ""
    assert "constitution key" in result.stderr
    remote.close.assert_called_once()


def test_given_server_selected_key_when_cli_current_yaml_runs_then_output_names_returned_key(
    monkeypatch, memory_store
):
    plane = ControlPlane(memory_store)
    version = plane.apply_direction(
        constitution_key="server-selected", mission="Server direction", change_note="Initial"
    )
    remote = Mock()
    remote.call_tool.return_value = version.to_dict()
    monkeypatch.setattr(cli, "dial", lambda *args, **kwargs: remote)

    result = runner.invoke(cli.app, ["current", "--yaml", "--remote"])

    assert result.exit_code == 0, result.output
    assert "constitution_key" not in remote.call_tool.call_args.args[1]
    assert yaml.safe_load(result.stdout)["constitution_key"] == "server-selected"


def test_given_returned_key_when_cli_get_version_number_yaml_runs_then_output_names_returned_key(
    monkeypatch, memory_store
):
    plane = ControlPlane(memory_store)
    plane.apply_direction(
        constitution_key="server-selected", mission="Server direction", change_note="Initial"
    )
    remote = Mock()
    remote.call_tool.return_value = plane.export_versions("server-selected")
    monkeypatch.setattr(cli, "dial", lambda *args, **kwargs: remote)

    result = runner.invoke(cli.app, ["get-version", "1", "--yaml", "--remote"])

    assert result.exit_code == 0, result.output
    assert "constitution_key" not in remote.call_tool.call_args.args[1]
    assert yaml.safe_load(result.stdout)["constitution_key"] == "server-selected"


def test_given_server_selected_key_when_cli_export_runs_then_output_names_returned_key(
    monkeypatch, memory_store
):
    plane = ControlPlane(memory_store)
    plane.apply_direction(
        constitution_key="server-selected", mission="Server direction", change_note="Initial"
    )
    remote = Mock()
    remote.call_tool.return_value = plane.export_versions("server-selected")
    monkeypatch.setattr(cli, "dial", lambda *args, **kwargs: remote)

    result = runner.invoke(cli.app, ["export", "--remote"])

    assert result.exit_code == 0, result.output
    assert "constitution_key" not in remote.call_tool.call_args.args[1]
    assert "Constitution 'server-selected' exported" in result.stderr
    assert json.loads(result.stdout)[0]["constitution_key"] == "server-selected"


def test_given_core_publication_identity_when_cli_publish_runs_then_output_names_returned_key(
    monkeypatch,
):
    plane = Mock()
    plane.publish.return_value.constitution_key = "core-selected"
    plane.publish.return_value.history_public = False
    monkeypatch.setattr(cli, "_control_plane", lambda: plane)

    result = runner.invoke(cli.app, ["publish"])

    assert result.exit_code == 0, result.output
    assert "'core-selected'" in result.stdout
    assert plane.publish.call_args.args[0] is None


def test_given_core_publication_identity_when_cli_unpublish_runs_then_output_names_returned_key(
    monkeypatch,
):
    plane = Mock()
    plane.unpublish.return_value.constitution_key = "core-selected"
    plane.unpublish.return_value.history_public = False
    monkeypatch.setattr(cli, "_control_plane", lambda: plane)

    result = runner.invoke(cli.app, ["unpublish"])

    assert result.exit_code == 0, result.output
    assert "'core-selected'" in result.stdout
    assert plane.unpublish.call_args.args[0] is None


def test_given_unwritten_server_target_when_cli_current_outputs_yaml_then_error_names_returned_key(
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


@pytest.mark.parametrize("identity", [{}, {"constitution_key": None}], ids=["absent", "null"])
@pytest.mark.parametrize(
    "options", [[], ["--constitution-key", "default"]], ids=["omitted", "explicit"]
)
def test_given_missing_response_key_when_cli_history_remote_runs_then_no_history_is_printed(
    monkeypatch, memory_store, identity, options
):
    row = (
        ControlPlane(memory_store).apply_direction(mission="Help", change_note="Initial").to_dict()
    )
    del row["constitution_key"]
    row.update(identity)
    remote = Mock()
    remote.call_tool.return_value = [row]
    monkeypatch.setattr(cli, "dial", lambda *args, **kwargs: remote)

    result = runner.invoke(cli.app, ["history", "--remote", *options])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "constitution key" in result.stderr
    remote.close.assert_called_once()


def test_given_omitted_destination_when_cli_import_then_data_is_written_to_core_selected_key(
    monkeypatch, memory_store, tmp_path
):
    plane = ControlPlane(memory_store)
    plane.apply_direction(
        constitution_key="source", mission="Support customers", change_note="Initial"
    )
    backup = tmp_path / "backup.json"
    backup.write_text(json.dumps(plane.export_versions("source")))
    core = Mock(wraps=plane)
    core.current.return_value = plane.current("selected-target")
    monkeypatch.setattr(cli, "_control_plane", lambda: core)
    monkeypatch.setattr(cli, "_store", lambda: memory_store)

    result = runner.invoke(cli.app, ["import", str(backup)])

    assert result.exit_code == 0, result.output
    core.current.assert_called_once_with(None)
    assert plane.current("selected-target").mission == "Support customers"
    assert plane.current("default").version == 0
    assert "into 'selected-target'" in result.stdout


def test_given_no_constitution_key_when_cli_current_yaml_runs_then_yaml_uses_core_selected_key(
    monkeypatch, memory_store
):
    plane = ControlPlane(memory_store)
    version = plane.apply_direction(
        constitution_key="support", mission="Help", change_note="Initial"
    )
    core = Mock()
    core.current.return_value = version
    monkeypatch.setattr(cli, "_control_plane", lambda: core)

    result = runner.invoke(cli.app, ["current", "--yaml"])

    assert result.exit_code == 0, result.output
    core.current.assert_called_once_with(None)
    assert yaml.safe_load(result.stdout)["constitution_key"] == "support"
