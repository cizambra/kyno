"""The whole deployment story on a clean machine, in one pass.

Every step here has focused tests of its own. This file proves they
compose: a fresh workspace, a real `kyno serve` process, tokens minted
and revoked, and the same commands a person would type at each step.
"""

import json
import os
import socket
import subprocess
import sys

import pytest
from typer.testing import CliRunner

from kyno.cli import app
from tests.servers import free_port, wait_until

runner = CliRunner()

_CLI = [sys.executable, "-c", "from kyno.cli import app; app()"]


def _a_workspace_with_a_database(tmp_path, monkeypatch, name):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["new", name]).exit_code == 0
    root = tmp_path / name
    monkeypatch.chdir(root)
    assert runner.invoke(app, ["db", "init"]).exit_code == 0
    return root


def _set_port(root, port):
    config = root / "config" / "server"
    config.write_text(config.read_text().replace("port = 2256", f"port = {port}"))


def _serve(root, home):
    return subprocess.Popen(
        [*_CLI, "serve", "--transport", "http"],
        cwd=root,
        env={**os.environ, "HOME": str(home)},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )


def _wait_up(port, proc):
    def accepting():
        if proc.poll() is not None:
            raise AssertionError(f"server exited early: {proc.stderr.read().decode()}")
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            return True
        except OSError:
            return False

    wait_until(accepting, "the server did not come up", timeout=30, interval=0.1)


def _stop(proc):
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=10)


def _mint_a_reader_and_a_writer(monkeypatch):
    reader = runner.invoke(app, ["token", "add", "agents", "--scope", "read"]).output.strip()
    writer = runner.invoke(app, ["token", "add", "operators", "--scope", "write"]).output.strip()
    assert reader.startswith("kyno_") and writer.startswith("kyno_")
    monkeypatch.setenv("AGENTS_TOKEN", reader)
    monkeypatch.setenv("OPERATORS_TOKEN", writer)


def _point_the_client_at_the_server(port):
    # The docs' wiring: values in variables, files holding only references.
    for profile, var in (("agents", "AGENTS_TOKEN"), ("operators", "OPERATORS_TOKEN")):
        added = runner.invoke(app, ["credentials", "add", "--profile", profile, "--token-env", var])
        assert added.exit_code == 0, added.output
    url = f"http://127.0.0.1:{port}"
    default = runner.invoke(app, ["remote", "add", "--url", url, "--credentials", "agents"])
    assert default.exit_code == 0, default.output
    ops = runner.invoke(
        app, ["remote", "add", "--profile", "ops", "--url", url, "--credentials", "operators"]
    )
    assert ops.exit_code == 0, ops.output


def _each_credential_is_seen_as_itself():
    r = runner.invoke(app, ["whoami", "--remote"])
    assert r.exit_code == 0, r.output
    assert r.output.strip() == "agents  read"
    r = runner.invoke(app, ["whoami", "--remote", "--profile", "ops"])
    assert r.output.strip() == "operators  write"


def _the_reader_reads_the_empty_instance():
    r = runner.invoke(app, ["current", "--remote"])
    assert r.exit_code == 0
    assert "no constitution set (version 0)" in r.output


def _a_direction_file(root):
    path = root / "c.yaml"
    path.write_text("constitution: default\nmission: Ship it\n", encoding="utf-8")
    return path


def _the_reader_cannot_write(direction):
    r = runner.invoke(
        app, ["set", str(direction), "--note", "first", "--remote", "--no-interactive"]
    )
    assert r.exit_code == 1
    assert "the server refused set_direction: 403 forbidden" in r.output


def _the_writer_writes_and_the_reader_sees_the_version(direction):
    r = runner.invoke(
        app,
        [
            "set",
            str(direction),
            "--note",
            "first",
            "--remote",
            "--no-interactive",
            "--profile",
            "ops",
        ],
    )
    assert r.exit_code == 0, r.output
    payload = json.loads(runner.invoke(app, ["current", "--remote"]).output)
    assert payload["version"] == 1 and payload["mission"] == "Ship it"


def _revoking_the_writer_shuts_it_out_and_leaves_the_reader_working():
    assert runner.invoke(app, ["token", "revoke", "operators"]).exit_code == 0
    r = runner.invoke(app, ["whoami", "--remote", "--profile", "ops"])
    assert r.exit_code == 1
    assert "refused the token: 401 unauthorized" in r.output
    assert runner.invoke(app, ["whoami", "--remote"]).exit_code == 0


@pytest.mark.e2e
def test_given_a_clean_environment_when_deploying_over_http_then_the_full_lifecycle_works(
    tmp_path, monkeypatch
):
    root = _a_workspace_with_a_database(tmp_path, monkeypatch, "acme")
    port = free_port()
    _set_port(root, port)

    # The server comes up with an empty token table, so an operator
    # can start it first and mint tokens afterwards.
    proc = _serve(root, tmp_path)
    try:
        _wait_up(port, proc)

        # Both tokens are minted while the server runs, and it honors
        # them without a restart.
        _mint_a_reader_and_a_writer(monkeypatch)
        _point_the_client_at_the_server(port)

        _each_credential_is_seen_as_itself()
        _the_reader_reads_the_empty_instance()

        direction = _a_direction_file(root)
        _the_reader_cannot_write(direction)
        _the_writer_writes_and_the_reader_sees_the_version(direction)

        _revoking_the_writer_shuts_it_out_and_leaves_the_reader_working()
    finally:
        _stop(proc)


@pytest.mark.e2e
def test_given_allow_insecure_in_a_clean_environment_when_serving_then_no_token_is_checked(
    tmp_path, monkeypatch
):
    root = _a_workspace_with_a_database(tmp_path, monkeypatch, "open")
    port = free_port()
    _set_port(root, port)
    config = root / "config" / "server"
    config.write_text(config.read_text().replace("[server]", "[server]\nallow_insecure = true"))

    # The client still holds a token, but this server never minted it and
    # never looks at it.
    monkeypatch.setenv("ANY_TOKEN", "kyno_never-minted")
    assert runner.invoke(app, ["credentials", "add", "--token-env", "ANY_TOKEN"]).exit_code == 0
    assert runner.invoke(app, ["remote", "add", "--url", f"http://127.0.0.1:{port}"]).exit_code == 0

    proc = _serve(root, tmp_path)
    try:
        _wait_up(port, proc)

        r = runner.invoke(app, ["whoami", "--remote"])
        assert r.exit_code == 0, r.output
        assert "no token: the server accepted the request without checking for one" in r.output

        r = runner.invoke(app, ["current", "--remote"])
        assert r.exit_code == 0
        assert "no constitution set (version 0)" in r.output
    finally:
        _stop(proc)
