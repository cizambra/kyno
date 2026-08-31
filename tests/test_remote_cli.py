"""--remote: the same five commands, dialing a profile's endpoint."""

import json
import pathlib
import re

import pytest
from typer.testing import CliRunner

import kyno.cli as cli
from kyno import mcp_server
from kyno.cli import app
from kyno.remote import RemoteError
from kyno.service import ControlPlane
from kyno.store.sql import SqlConstitutionStore

runner = CliRunner()


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    (tmp_path / "work").mkdir()
    monkeypatch.chdir(tmp_path / "work")
    monkeypatch.setenv("KYNO_DATABASE_URL", f"sqlite:///{tmp_path / 'local.sqlite3'}")
    return tmp_path


def plain(output):
    return " ".join(re.sub(r"\x1b\[[0-9;]*m", "", output).split())


def write_file(dirpath, mission="M1", name="c.yaml", constitution="default"):
    path = pathlib.Path(dirpath) / name
    path.write_text(f"constitution: {constitution}\nmission: {mission}\n", encoding="utf-8")
    return str(path)


class FakeRemote:
    """What dial() answers in tests: the real dispatch handlers over a real
    control plane, minus the network. Refusals surface the way the wire
    surfaces them: as RemoteError carrying the server's words."""

    def __init__(self, cp):
        self.cp = cp
        self.closed = False
        self.url = "https://fake.kyno.test"

    def call_tool(self, name, arguments):
        try:
            if name == "get_constitution":
                result = mcp_server.handle_get_constitution(
                    self.cp, arguments.get("constitution"), arguments.get("detail", "compact")
                )
            elif name == "export_versions":
                result = mcp_server.handle_export_versions(
                    self.cp,
                    arguments.get("constitution"),
                    from_version=arguments.get("from_version"),
                    to_version=arguments.get("to_version"),
                )
            elif name == "set_direction":
                result = mcp_server.handle_set_direction(
                    self.cp,
                    mission=arguments.get("mission"),
                    declaration=arguments.get("declaration"),
                    principles=arguments.get("principles"),
                    change_note=arguments["change_note"],
                    created_by=arguments.get("created_by"),
                    constitution=arguments.get("constitution"),
                    expected_version=arguments.get("expected_version"),
                )
            else:
                raise ValueError(f"unknown tool: {name}")
        except ValueError as exc:
            raise RemoteError(str(exc)) from exc
        if name == "get_constitution" and self.after_fetch is not None:
            hook, self.after_fetch = self.after_fetch, None
            hook()
        return json.loads(json.dumps(result))

    def close(self):
        self.closed = True

    # A hook for race tests: runs after the head is served, before the write.
    after_fetch = None


@pytest.fixture
def remote_cp():
    store = SqlConstitutionStore(url="sqlite://")
    store.create_all()
    return ControlPlane(store)


@pytest.fixture
def fake_dial(remote_cp, monkeypatch):
    fake = FakeRemote(remote_cp)
    fake.dialed = {}

    def dial(profile, *, credentials_profile=None, token_env=None):
        fake.dialed.update(profile=profile, credentials=credentials_profile, token_env=token_env)
        return fake

    monkeypatch.setattr(cli, "dial", dial)
    return fake


def test_given_a_remote_head_when_reading_current_remotely_then_it_prints(fake_dial, remote_cp):
    remote_cp.set_direction(mission="M-remote", change_note="init")
    r = runner.invoke(app, ["current", "--remote"])
    assert r.exit_code == 0, r.output
    assert json.loads(r.stdout)["mission"] == "M-remote"
    assert fake_dial.closed


def test_given_an_empty_remote_when_reading_current_remotely_then_version_0_reports(fake_dial):
    r = runner.invoke(app, ["current", "--remote"])
    assert r.exit_code == 0 and "no constitution set (version 0)" in r.output


def test_given_a_remote_head_when_reading_current_yaml_remotely_then_the_file_format_prints(
    fake_dial, remote_cp
):
    remote_cp.set_direction(mission="M-remote", change_note="init")
    r = runner.invoke(app, ["current", "--remote", "--yaml"])
    assert r.exit_code == 0
    assert "constitution: default" in r.stdout and "mission: M-remote" in r.stdout


def test_given_a_file_when_applying_remotely_then_the_delta_shows_and_the_version_is_applied(
    fake_dial, remote_cp, tmp_path
):
    path = write_file(tmp_path, mission="Ship it")
    r = runner.invoke(
        app,
        ["set", path, "--note", "over the wire", "--remote", "--by", "camilo", "--no-interactive"],
    )
    assert r.exit_code == 0, r.output
    assert "Creates 'default' at version 1." in r.output
    assert json.loads(r.stdout)["version"] == 1
    assert remote_cp.current().mission == "Ship it"
    assert remote_cp.current().created_by == "camilo"


def test_given_identical_content_when_applying_remotely_then_it_is_a_clean_no_op(
    fake_dial, remote_cp, tmp_path
):
    remote_cp.set_direction(mission="Same", change_note="init")
    path = write_file(tmp_path, mission="Same")
    r = runner.invoke(app, ["set", path, "--note", "again", "--remote", "--no-interactive"])
    assert r.exit_code == 0, r.output
    assert "no field changed" in r.output
    assert json.loads(r.stdout)["version"] == 1
    assert remote_cp.current().version == 1


def test_given_dry_run_when_applying_remotely_then_the_delta_prints_and_nothing_lands_there(
    fake_dial, remote_cp, tmp_path
):
    path = write_file(tmp_path, mission="Draft")
    r = runner.invoke(app, ["set", path, "--dry-run", "--remote"])
    assert r.exit_code == 0
    assert "Creates 'default' at version 1." in r.output
    assert remote_cp.current().version == 0


def test_given_a_matching_file_when_checking_remotely_then_the_store_agrees(
    fake_dial, remote_cp, tmp_path
):
    remote_cp.set_direction(mission="M1", change_note="init")
    path = write_file(tmp_path, mission="M1")
    r = runner.invoke(app, ["check", path, "--remote"])
    assert r.exit_code == 0, r.output
    assert "store: agrees with 'default' (version 1)" in r.output


def test_given_a_stale_file_when_checking_remotely_then_it_fails_with_the_delta(
    fake_dial, remote_cp, tmp_path
):
    remote_cp.set_direction(mission="M1", change_note="init")
    path = write_file(tmp_path, mission="M2")
    r = runner.invoke(app, ["check", path, "--remote"])
    assert r.exit_code == 1
    assert "store: differs from 'default' (version 1):" in r.output
    assert 'The mission was "M1" and is now "M2".' in r.output


def test_given_an_unreachable_endpoint_when_checking_remotely_then_not_compared_exit_0(
    monkeypatch, tmp_path
):
    def dial(profile, **_):
        raise RemoteError(f"cannot reach '{profile}' at https://kyno.mybiz.com: refused")

    monkeypatch.setattr(cli, "dial", dial)
    path = write_file(tmp_path, mission="M1")
    r = runner.invoke(app, ["check", path, "--remote"])
    assert r.exit_code == 0
    assert "kyno fields set: constitution, mission" in r.output
    assert "store: not compared (cannot reach 'default'" in r.output


def test_given_remote_history_when_reading_log_remotely_then_the_lines_print(fake_dial, remote_cp):
    remote_cp.set_direction(mission="M1", change_note="init", created_by="camilo")
    remote_cp.set_direction(mission="M2", change_note="pivot", created_by="ci")
    r = runner.invoke(app, ["log", "--remote"])
    assert r.exit_code == 0
    lines = r.stdout.strip().splitlines()
    assert lines[0].startswith("v2") and "pivot" in lines[0]
    assert lines[1].startswith("v1") and "camilo" in lines[1]


def test_given_remote_history_when_exporting_remotely_then_the_rows_print(fake_dial, remote_cp):
    remote_cp.set_direction(mission="M1", change_note="init")
    r = runner.invoke(app, ["export", "--remote"])
    assert r.exit_code == 0
    rows = json.loads(r.stdout)
    assert [row["version"] for row in rows] == [1]


def test_given_remote_flags_when_dialing_then_they_pass_through(fake_dial, remote_cp):
    remote_cp.set_direction(mission="M1", change_note="init")
    r = runner.invoke(app, ["current", "--remote", "--profile", "oncall", "--credentials", "ops"])
    assert r.exit_code == 0, r.output
    assert fake_dial.dialed == {"profile": "oncall", "credentials": "ops", "token_env": None}


@pytest.mark.parametrize(
    "args",
    [
        ["current", "--profile", "oncall"],
        ["log", "--credentials", "ops"],
        ["export", "--token-env", "T"],
    ],
)
def test_given_remote_only_flags_without_remote_when_running_then_it_is_refused(args):
    r = runner.invoke(app, args)
    assert r.exit_code != 0
    assert "add --remote" in plain(r.output)


def test_given_no_profiles_when_going_remote_then_the_error_names_have_and_fix():
    r = runner.invoke(app, ["current", "--remote"])
    assert r.exit_code == 1
    assert "error: no remote profile 'default'; you have: none" in plain(r.output)


@pytest.mark.e2e
def test_given_a_live_server_when_applying_remotely_then_the_version_is_applied(
    tmp_path, monkeypatch
):
    """The one true end-to-end: a real HTTP server, the real bearer gate,
    the real client. Everything else in this file skips the wire."""
    import socket
    import threading
    import time

    import uvicorn

    from kyno.transports import build_http_app

    store = SqlConstitutionStore(url=f"sqlite:///{tmp_path / 'server.sqlite3'}")
    store.create_all()
    http_app = build_http_app(ControlPlane(store), token="s3cret")
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    server = uvicorn.Server(
        uvicorn.Config(http_app, host="127.0.0.1", port=port, log_level="error")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(200):
            if server.started:
                break
            time.sleep(0.05)
        assert server.started, "uvicorn did not come up"
        monkeypatch.setenv("MY_TOKEN", "s3cret")
        assert runner.invoke(app, ["credentials", "add", "--token-env", "MY_TOKEN"]).exit_code == 0
        assert (
            runner.invoke(app, ["remote", "add", "--url", f"http://127.0.0.1:{port}"]).exit_code
            == 0
        )
        path = write_file(tmp_path, mission="Live over the wire")
        r = runner.invoke(app, ["set", path, "--note", "e2e", "--remote", "--no-interactive"])
        assert r.exit_code == 0, r.output
        assert store.head("default").mission == "Live over the wire"
        r = runner.invoke(app, ["log", "--remote"])
        assert r.exit_code == 0 and "e2e" in r.stdout
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def test_given_a_writer_racing_in_mid_apply_when_applying_remotely_then_nothing_is_applied(
    fake_dial, remote_cp, tmp_path
):
    """The delta was computed against the head we fetched; if the head moves
    before the write, the server refuses instead of applying an edit nobody
    reviewed in that shape."""
    remote_cp.set_direction(mission="M1", change_note="init")
    fake_dial.after_fetch = lambda: remote_cp.set_direction(
        mission="Raced in", change_note="someone else"
    )
    path = write_file(tmp_path, mission="M2")
    r = runner.invoke(app, ["set", path, "--note", "stale", "--remote", "--no-interactive"])
    assert r.exit_code == 1
    assert "moved while applying; read it again and re-apply" in r.output
    assert remote_cp.current().mission == "Raced in" and remote_cp.current().version == 2


def test_given_a_yes_at_the_consent_question_when_applying_remotely_then_the_version_is_applied(
    fake_dial, remote_cp, tmp_path
):
    path = write_file(tmp_path, mission="M1")
    r = runner.invoke(app, ["set", path, "--note", "init", "--remote"], input="y\n")
    assert r.exit_code == 0, r.output
    assert "Have you evaluated it against your workflow?" in r.output
    assert remote_cp.current().version == 1


def test_given_a_no_at_the_consent_question_when_applying_remotely_then_nothing_is_applied(
    fake_dial, remote_cp, tmp_path
):
    path = write_file(tmp_path, mission="M1")
    r = runner.invoke(app, ["set", path, "--note", "init", "--remote"], input="n\n")
    assert r.exit_code == 1
    assert "not applied: the consent question was answered no" in r.output
    assert remote_cp.current().version == 0


def test_given_nobody_at_the_keyboard_when_the_consent_question_asks_then_nothing_is_applied(
    fake_dial, remote_cp, tmp_path
):
    """Without --no-interactive and without stdin, the command fails and
    the error says what to pass, instead of hanging or trying to guess
    whether a terminal is attached."""
    path = write_file(tmp_path, mission="M1")
    r = runner.invoke(app, ["set", path, "--note", "init", "--remote"])
    assert r.exit_code == 1
    assert "nobody to answer it" in r.output
    assert "--no-interactive" in r.output and "--unsafe-approval" in r.output
    assert remote_cp.current().version == 0


def test_given_unsafe_approval_when_applying_remotely_then_no_question_is_asked(
    fake_dial, remote_cp, tmp_path
):
    path = write_file(tmp_path, mission="M1")
    r = runner.invoke(app, ["set", path, "--note", "init", "--remote", "--unsafe-approval"])
    assert r.exit_code == 0, r.output
    assert "evaluated it against your workflow" not in r.output
    assert remote_cp.current().version == 1


def test_given_no_interactive_when_applying_remotely_then_no_question_is_asked(
    fake_dial, remote_cp, tmp_path
):
    """CI passes --no-interactive and is never asked anything."""
    path = write_file(tmp_path, mission="M1")
    r = runner.invoke(app, ["set", path, "--note", "init", "--remote", "--no-interactive"])
    assert r.exit_code == 0, r.output
    assert "evaluated it against your workflow" not in r.output


def test_given_a_local_apply_when_running_set_then_no_question_is_asked(tmp_path, monkeypatch):
    monkeypatch.setenv("KYNO_DATABASE_URL", f"sqlite:///{tmp_path / 'c.sqlite3'}")
    runner.invoke(app, ["init-db"])
    path = write_file(tmp_path, mission="M1")
    r = runner.invoke(app, ["set", path, "--note", "init"])
    assert r.exit_code == 0, r.output
    assert "evaluated it against your workflow" not in r.output


def test_given_a_dry_run_when_applying_remotely_then_no_question_is_asked(
    fake_dial, remote_cp, tmp_path
):
    path = write_file(tmp_path, mission="M1")
    r = runner.invoke(app, ["set", path, "--dry-run", "--remote"])
    assert r.exit_code == 0, r.output
    assert "evaluated it against your workflow" not in r.output


@pytest.mark.parametrize("flag", ["--no-interactive", "--unsafe-approval"])
def test_given_a_question_flag_without_remote_when_applying_then_it_is_refused(
    tmp_path, monkeypatch, flag
):
    monkeypatch.setenv("KYNO_DATABASE_URL", f"sqlite:///{tmp_path / 'c.sqlite3'}")
    path = write_file(tmp_path, mission="M1")
    r = runner.invoke(app, ["set", path, "--note", "init", flag])
    assert r.exit_code != 0
    assert "add --remote" in plain(r.output)


def test_given_both_question_flags_when_applying_then_it_is_refused_as_redundant(
    fake_dial, remote_cp, tmp_path
):
    """The flags are two different ways to skip the questions, so passing
    both means nothing extra; Kyno asks you to pick one."""
    path = write_file(tmp_path, mission="M1")
    r = runner.invoke(
        app, ["set", path, "--note", "init", "--remote", "--no-interactive", "--unsafe-approval"]
    )
    assert r.exit_code != 0
    assert "pick one" in plain(r.output)
    assert remote_cp.current().version == 0
