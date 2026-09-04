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
import time

import pytest
from typer.testing import CliRunner

from kyno.cli import app

runner = CliRunner()

_CLI = [sys.executable, "-c", "from kyno.cli import app; app()"]


def _free_port():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


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
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise AssertionError(f"server exited early: {proc.stderr.read().decode()}")
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            return
        except OSError:
            time.sleep(0.1)
    raise AssertionError("server did not come up in 30s")


def _stop(proc):
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=10)


@pytest.mark.e2e
def test_given_a_clean_environment_when_deploying_over_http_then_the_full_lifecycle_works(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.chdir(tmp_path)

    assert runner.invoke(app, ["new", "acme"]).exit_code == 0
    root = tmp_path / "acme"
    monkeypatch.chdir(root)
    assert runner.invoke(app, ["db", "init"]).exit_code == 0
    port = _free_port()
    _set_port(root, port)

    # Serving before any token exists refuses, naming the fix.
    early = subprocess.run(
        [*_CLI, "serve", "--transport", "http"],
        cwd=root,
        env={**os.environ, "HOME": str(tmp_path)},
        capture_output=True,
        timeout=60,
    )
    assert early.returncode == 1
    assert b"no live tokens" in early.stderr

    # Mint one credential per audience, and wire the client side the way
    # the docs say: values in variables, files holding only references.
    read_value = runner.invoke(app, ["token", "add", "agents", "--scope", "read"]).output.strip()
    writer = runner.invoke(app, ["token", "add", "operators", "--scope", "write"]).output.strip()
    assert read_value.startswith("kyno_") and writer.startswith("kyno_")
    monkeypatch.setenv("AGENTS_TOKEN", read_value)
    monkeypatch.setenv("OPERATORS_TOKEN", writer)
    for profile, var in (("agents", "AGENTS_TOKEN"), ("operators", "OPERATORS_TOKEN")):
        added = runner.invoke(app, ["credentials", "add", "--profile", profile, "--token-env", var])
        assert added.exit_code == 0, added.output
    url = f"http://127.0.0.1:{port}"
    assert (
        runner.invoke(app, ["remote", "add", "--url", url, "--credentials", "agents"]).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            ["remote", "add", "--profile", "ops", "--url", url, "--credentials", "operators"],
        ).exit_code
        == 0
    )

    proc = _serve(root, tmp_path)
    try:
        _wait_up(port, proc)

        # Each credential is seen as itself.
        r = runner.invoke(app, ["whoami", "--remote"])
        assert r.exit_code == 0, r.output
        assert r.output.strip() == "agents  read"
        r = runner.invoke(app, ["whoami", "--remote", "--profile", "ops"])
        assert r.output.strip() == "operators  write"

        # The read credential reads the empty instance.
        r = runner.invoke(app, ["current", "--remote"])
        assert r.exit_code == 0
        assert "no constitution set (version 0)" in r.output

        # The read credential cannot write.
        direction = root / "c.yaml"
        direction.write_text("constitution: default\nmission: Ship it\n", encoding="utf-8")
        r = runner.invoke(
            app, ["set", str(direction), "--note", "first", "--remote", "--no-interactive"]
        )
        assert r.exit_code == 1
        assert "the server refused set_direction: 403 forbidden" in r.output

        # The write credential writes, and the reader sees the version.
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

        # Revoking the write token shuts its holder out on the next dial,
        # with the refusal named; the read credential keeps working.
        assert runner.invoke(app, ["token", "revoke", "operators"]).exit_code == 0
        r = runner.invoke(app, ["whoami", "--remote", "--profile", "ops"])
        assert r.exit_code == 1
        assert "refused the token: 401 unauthorized" in r.output
        assert runner.invoke(app, ["whoami", "--remote"]).exit_code == 0
    finally:
        _stop(proc)


@pytest.mark.e2e
def test_given_allow_insecure_in_a_clean_environment_when_serving_then_no_token_is_checked(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.chdir(tmp_path)

    assert runner.invoke(app, ["new", "open"]).exit_code == 0
    root = tmp_path / "open"
    monkeypatch.chdir(root)
    assert runner.invoke(app, ["db", "init"]).exit_code == 0
    port = _free_port()
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
