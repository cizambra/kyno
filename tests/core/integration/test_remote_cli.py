"""Remote CLI behavior through the fake remote/control-plane seam."""

import json
import pathlib
from datetime import UTC, datetime

import pytest

import kyno.cli as cli
from kyno import mcp_server
from kyno.cli import app
from kyno.models import AuthorizationType, Token
from kyno.remote import RemoteError
from kyno.service import ControlPlane
from kyno.store.sql import SqlConstitutionStore
from tests.remote_cli import plain, runner, write_file
from tests.workspaces import cli_workspace


@pytest.fixture(autouse=True)
def home(remote_cli_home):
    return remote_cli_home


class FakeRemote:
    """What dial() answers in tests: real dispatch handlers over a real
    control plane, minus the network."""

    def __init__(self, cp):
        self.cp = cp
        self.closed = False
        self.url = "https://fake.kyno.test"
        self.token = None

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
                    authorized_by=arguments.get("authorized_by"),
                )
            elif name == "whoami":
                result = mcp_server.handle_whoami(self.token)
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


def _three_versions(remote_cp):
    remote_cp.set_direction(mission="M1", change_note="v1")
    remote_cp.set_direction(mission="M2", change_note="v2")
    remote_cp.set_direction(mission="M3", change_note="v3")


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
        [
            "apply",
            path,
            "--note",
            "over the wire",
            "--remote",
            "--by",
            "camilo",
            "--no-interactive",
        ],
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
    r = runner.invoke(app, ["apply", path, "--note", "again", "--remote", "--no-interactive"])
    assert r.exit_code == 0, r.output
    assert "no field changed" in r.output
    assert json.loads(r.stdout)["version"] == 1
    assert remote_cp.current().version == 1


def test_given_dry_run_when_applying_remotely_then_the_delta_prints_and_nothing_lands_there(
    fake_dial, remote_cp, tmp_path
):
    path = write_file(tmp_path, mission="Draft")
    r = runner.invoke(app, ["apply", path, "--dry-run", "--remote"])
    assert r.exit_code == 0
    assert "Creates 'default' at version 1." in r.output
    assert remote_cp.current().version == 0


def test_given_a_matching_file_when_checking_remotely_then_it_matches_current_direction(
    fake_dial, remote_cp, tmp_path
):
    remote_cp.set_direction(mission="M1", change_note="init")
    path = write_file(tmp_path, mission="M1")
    r = runner.invoke(app, ["check", path, "--remote"])
    assert r.exit_code == 0, r.output
    assert "direction: 'default' matches current version 1" in r.output


def test_given_a_stale_file_when_checking_remotely_then_it_fails_with_the_delta(
    fake_dial, remote_cp, tmp_path
):
    remote_cp.set_direction(mission="M1", change_note="init")
    path = write_file(tmp_path, mission="M2")
    r = runner.invoke(app, ["check", path, "--remote"])
    assert r.exit_code == 1
    assert "direction: 'default' differs from current version 1:" in r.output
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
    assert "kyno fields present: constitution, mission" in r.output
    assert "direction: not compared (cannot reach 'default'" in r.output


def test_given_remote_history_when_reading_history_remotely_then_the_lines_print(
    fake_dial, remote_cp
):
    remote_cp.set_direction(mission="M1", change_note="init", created_by="camilo")
    remote_cp.set_direction(mission="M2", change_note="pivot", created_by="ci")
    r = runner.invoke(app, ["history", "--remote"])
    assert r.exit_code == 0
    lines = r.stdout.strip().splitlines()
    assert lines[0].startswith("v2") and "pivot" in lines[0]
    assert lines[1].startswith("v1") and "camilo" in lines[1]


def test_given_remote_history_when_exporting_remotely_then_rows_and_the_stderr_line_print(
    fake_dial, remote_cp
):
    # The stderr line needs no server data -- the name is the one the
    # caller asked for -- so it prints on remote exports too.
    remote_cp.set_direction(mission="M1", change_note="init")
    r = runner.invoke(app, ["export", "--remote"])
    assert r.exit_code == 0
    assert "Constitution 'default' exported" in r.stderr
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
        ["history", "--credentials", "ops"],
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


def test_given_a_writer_racing_in_mid_apply_when_applying_remotely_then_nothing_is_applied(
    fake_dial, remote_cp, tmp_path
):
    """The delta was computed against the head we fetched. If the head moves
    before the write, the server refuses instead of applying an edit that was
    never reviewed against the new head."""
    remote_cp.set_direction(mission="M1", change_note="init")
    fake_dial.after_fetch = lambda: remote_cp.set_direction(
        mission="Raced in", change_note="someone else"
    )
    path = write_file(tmp_path, mission="M2")
    r = runner.invoke(app, ["apply", path, "--note", "stale", "--remote", "--no-interactive"])
    assert r.exit_code == 1
    assert "moved while applying; read it again and re-apply" in r.output
    assert remote_cp.current().mission == "Raced in" and remote_cp.current().version == 2


def test_given_a_yes_at_the_consent_question_when_applying_remotely_then_the_version_is_applied(
    fake_dial, remote_cp, tmp_path
):
    path = write_file(tmp_path, mission="M1")
    r = runner.invoke(app, ["apply", path, "--note", "init", "--remote"], input="y\n")
    assert r.exit_code == 0, r.output
    assert "Have you evaluated it against your workflow?" in r.output
    assert (
        "The updated direction is available to agents on subsequent successful pulls." in r.output
    )
    assert remote_cp.current().version == 1


def test_given_a_no_at_the_consent_question_when_applying_remotely_then_nothing_is_applied(
    fake_dial, remote_cp, tmp_path
):
    path = write_file(tmp_path, mission="M1")
    r = runner.invoke(app, ["apply", path, "--note", "init", "--remote"], input="n\n")
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
    r = runner.invoke(app, ["apply", path, "--note", "init", "--remote"])
    assert r.exit_code == 1
    assert "nobody to answer it" in r.output
    assert "--no-interactive" in r.output and "--unsafe-approval" in r.output
    assert remote_cp.current().version == 0


def test_given_unsafe_approval_when_applying_remotely_then_no_question_is_asked(
    fake_dial, remote_cp, tmp_path
):
    path = write_file(tmp_path, mission="M1")
    r = runner.invoke(app, ["apply", path, "--note", "init", "--remote", "--unsafe-approval"])
    assert r.exit_code == 0, r.output
    assert "evaluated it against your workflow" not in r.output
    assert remote_cp.current().version == 1


def test_given_no_interactive_when_applying_remotely_then_no_question_is_asked(
    fake_dial, remote_cp, tmp_path
):
    """CI passes --no-interactive and is never asked anything."""
    path = write_file(tmp_path, mission="M1")
    r = runner.invoke(app, ["apply", path, "--note", "init", "--remote", "--no-interactive"])
    assert r.exit_code == 0, r.output
    assert "evaluated it against your workflow" not in r.output


def test_given_a_local_apply_when_running_apply_then_no_question_is_asked(tmp_path, monkeypatch):
    cli_workspace(monkeypatch, tmp_path, tmp_path / "c.sqlite3")
    runner.invoke(app, ["db", "init"])
    path = write_file(tmp_path, mission="M1")
    r = runner.invoke(app, ["apply", path, "--note", "init"])
    assert r.exit_code == 0, r.output
    assert "evaluated it against your workflow" not in r.output


def test_given_a_dry_run_when_applying_remotely_then_no_question_is_asked(
    fake_dial, remote_cp, tmp_path
):
    path = write_file(tmp_path, mission="M1")
    r = runner.invoke(app, ["apply", path, "--dry-run", "--remote"])
    assert r.exit_code == 0, r.output
    assert "evaluated it against your workflow" not in r.output


@pytest.mark.parametrize("flag", ["--no-interactive", "--unsafe-approval"])
def test_given_a_question_flag_without_remote_when_applying_then_it_is_refused(
    tmp_path, monkeypatch, flag
):
    monkeypatch.setenv("KYNO_DATABASE_URL", f"sqlite:///{tmp_path / 'c.sqlite3'}")
    path = write_file(tmp_path, mission="M1")
    r = runner.invoke(app, ["apply", path, "--note", "init", flag])
    assert r.exit_code != 0
    assert "add --remote" in plain(r.output)


def test_given_both_question_flags_when_applying_then_it_is_refused_as_redundant(
    fake_dial, remote_cp, tmp_path
):
    """The flags are two different ways to skip the questions, so passing
    both means nothing extra; Kyno asks you to pick one."""
    path = write_file(tmp_path, mission="M1")
    r = runner.invoke(
        app, ["apply", path, "--note", "init", "--remote", "--no-interactive", "--unsafe-approval"]
    )
    assert r.exit_code != 0
    assert "pick one" in plain(r.output)
    assert remote_cp.current().version == 0


def test_given_an_older_versions_content_when_applying_interactively_then_the_revert_asks(
    fake_dial, remote_cp, tmp_path
):
    _three_versions(remote_cp)
    path = write_file(tmp_path, mission="M1")
    r = runner.invoke(app, ["apply", path, "--note", "back to v1", "--remote"], input="y\ny\n")
    assert r.exit_code == 0, r.output
    assert "the same content as v1" in r.output and "back as v4" in r.output
    assert remote_cp.current().version == 4 and remote_cp.current().mission == "M1"


def test_given_a_no_at_the_revert_question_when_applying_then_nothing_is_applied(
    fake_dial, remote_cp, tmp_path
):
    _three_versions(remote_cp)
    path = write_file(tmp_path, mission="M1")
    r = runner.invoke(app, ["apply", path, "--note", "back", "--remote"], input="y\nn\n")
    assert r.exit_code == 1
    assert "not applied: the revert question was answered no" in r.output
    assert remote_cp.current().version == 3


def test_given_fresh_content_when_applying_interactively_then_only_consent_is_asked(
    fake_dial, remote_cp, tmp_path
):
    _three_versions(remote_cp)
    path = write_file(tmp_path, mission="M4")
    r = runner.invoke(app, ["apply", path, "--note", "new", "--remote"], input="y\n")
    assert r.exit_code == 0, r.output
    assert "deliberate revert" not in r.output


def test_given_an_older_versions_content_when_applying_headless_then_no_question_fires(
    fake_dial, remote_cp, tmp_path
):
    """A headless run can't tell a deliberate revert from a stale file, so
    it isn't asked; in CI the parent-commit comparison covers this case."""
    _three_versions(remote_cp)
    path = write_file(tmp_path, mission="M1")
    r = runner.invoke(app, ["apply", path, "--note", "back", "--remote", "--no-interactive"])
    assert r.exit_code == 0, r.output
    assert "revert" not in r.output
    assert remote_cp.current().version == 4


def test_given_unsafe_approval_when_re_landing_old_content_then_it_proceeds_unasked(
    fake_dial, remote_cp, tmp_path
):
    _three_versions(remote_cp)
    path = write_file(tmp_path, mission="M1")
    r = runner.invoke(app, ["apply", path, "--note", "back", "--remote", "--unsafe-approval"])
    assert r.exit_code == 0, r.output
    assert "deliberate revert" not in r.output and remote_cp.current().version == 4


def test_given_content_equal_to_the_head_when_applying_interactively_then_no_revert_asks(
    fake_dial, remote_cp, tmp_path
):
    """Only versions below the head count as a revert; matching the head is
    the ordinary no-op."""
    _three_versions(remote_cp)
    path = write_file(tmp_path, mission="M3")
    r = runner.invoke(app, ["apply", path, "--note", "same", "--remote"], input="y\n")
    assert r.exit_code == 0, r.output
    assert "deliberate revert" not in r.output
    assert "no field changed" in r.output
    assert remote_cp.current().version == 3


def test_given_two_older_versions_with_the_same_content_when_asking_then_the_newest_is_named(
    fake_dial, remote_cp, tmp_path
):
    remote_cp.set_direction(mission="M1", change_note="v1")
    remote_cp.set_direction(mission="M2", change_note="v2")
    remote_cp.set_direction(mission="M1", change_note="v3, back to v1")
    remote_cp.set_direction(mission="M4", change_note="v4")
    path = write_file(tmp_path, mission="M1")
    r = runner.invoke(app, ["apply", path, "--note", "back", "--remote"], input="y\ny\n")
    assert r.exit_code == 0, r.output
    assert "the same content as v3." in r.output and "as v1." not in r.output


def test_given_a_file_omitting_fields_when_carry_forward_matches_an_old_version_then_it_asks(
    fake_dial, remote_cp, tmp_path
):
    """The comparison uses the effective content: what the apply would
    write after omitted fields carry forward from the head."""
    remote_cp.set_direction(mission="M1", principles=["p1"], change_note="v1")
    remote_cp.set_direction(mission="M2", principles=["p1"], change_note="v2")
    # The file omits principles; p1 carries forward, so the result is v1.
    path = write_file(tmp_path, mission="M1")
    r = runner.invoke(app, ["apply", path, "--note", "back", "--remote"], input="y\ny\n")
    assert r.exit_code == 0, r.output
    assert "the same content as v1." in r.output


def test_given_the_same_mission_but_different_principles_when_applying_then_no_revert_asks(
    fake_dial, remote_cp, tmp_path
):
    remote_cp.set_direction(mission="M1", principles=["p1"], change_note="v1")
    remote_cp.set_direction(mission="M2", principles=["p1"], change_note="v2")
    p = pathlib.Path(tmp_path) / "c.yaml"
    p.write_text("constitution: default\nmission: M1\nprinciples:\n  - p2\n", encoding="utf-8")
    r = runner.invoke(app, ["apply", str(p), "--note", "new mix", "--remote"], input="y\n")
    assert r.exit_code == 0, r.output
    assert "deliberate revert" not in r.output


def test_given_stdin_ending_at_the_revert_prompt_when_applying_then_nothing_is_applied(
    fake_dial, remote_cp, tmp_path
):
    _three_versions(remote_cp)
    path = write_file(tmp_path, mission="M1")
    r = runner.invoke(app, ["apply", path, "--note", "back", "--remote"], input="y\n")
    assert r.exit_code == 1
    assert "not applied: the revert question had nobody to answer it" in r.output
    assert remote_cp.current().version == 3


def test_given_an_empty_remote_when_reading_current_yaml_then_nothing_to_read_exits_1(fake_dial):
    r = runner.invoke(app, ["current", "--remote", "--yaml"])
    assert r.exit_code == 1
    assert "nothing to read: 'default' has no versions" in r.output


def test_given_a_file_without_a_constitution_key_when_checking_remotely_then_not_compared(
    fake_dial, tmp_path
):
    target = pathlib.Path(tmp_path) / "unnamed.yaml"
    target.write_text("mission: M1\n", encoding="utf-8")
    r = runner.invoke(app, ["check", str(target), "--remote"])
    assert r.exit_code == 1
    assert "kyno fields omitted: constitution" in r.output
    assert "direction: not compared" in r.output and "constitution: <name>" in r.output


def test_given_dial_failing_when_reading_history_remotely_then_the_error_is_one_line(monkeypatch):
    def dial(profile, **_):
        raise RemoteError(f"cannot reach '{profile}' at https://kyno.mybiz.com: refused")

    monkeypatch.setattr(cli, "dial", dial)
    r = runner.invoke(app, ["history", "--remote"])
    assert r.exit_code == 1
    assert "error: cannot reach 'default'" in r.output and "Traceback" not in r.output


def test_given_a_person_answering_yes_when_applying_then_person_answered_is_recorded(
    fake_dial, remote_cp, tmp_path
):
    path = write_file(tmp_path, mission="M1")
    r = runner.invoke(app, ["apply", path, "--note", "init", "--remote"], input="y\n")
    assert r.exit_code == 0, r.output
    assert remote_cp.current().authorized_by is AuthorizationType.OPERATOR


def test_given_no_interactive_when_applying_then_automation_is_recorded(
    fake_dial, remote_cp, tmp_path
):
    path = write_file(tmp_path, mission="M1")
    r = runner.invoke(app, ["apply", path, "--note", "init", "--remote", "--no-interactive"])
    assert r.exit_code == 0, r.output
    assert remote_cp.current().authorized_by is AuthorizationType.AUTOMATION


def test_given_unsafe_approval_when_applying_then_unsafe_approved_is_recorded(
    fake_dial, remote_cp, tmp_path
):
    path = write_file(tmp_path, mission="M1")
    r = runner.invoke(app, ["apply", path, "--note", "init", "--remote", "--unsafe-approval"])
    assert r.exit_code == 0, r.output
    assert remote_cp.current().authorized_by is AuthorizationType.OVERRIDE


def test_given_recorded_authorizations_when_reading_history_remotely_then_authorized_by_is_printed(
    fake_dial, remote_cp, tmp_path
):
    path = write_file(tmp_path, mission="M1")
    runner.invoke(app, ["apply", path, "--note", "init", "--remote", "--unsafe-approval"])
    r = runner.invoke(app, ["history", "--remote"])
    assert r.exit_code == 0
    assert "override" in r.stdout


def test_given_no_credentials_when_listing_then_it_says_how_to_add_one(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    r = runner.invoke(app, ["credentials", "list"])
    assert r.exit_code == 0
    assert "kyno credentials add" in r.output


def test_given_stored_and_referenced_tokens_when_listing_then_values_never_print(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MY_CI_TOKEN", "kyno_secret-value")
    monkeypatch.delenv("MY_LAPTOP_TOKEN", raising=False)
    assert runner.invoke(app, ["credentials", "add", "--token-env", "MY_CI_TOKEN"]).exit_code == 0
    assert (
        runner.invoke(
            app, ["credentials", "add", "--profile", "ci2", "--token-env", "MY_LAPTOP_TOKEN"]
        ).exit_code
        == 0
    )
    r = runner.invoke(app, ["credentials", "add", "--profile", "typed"], input="typed-secret\n")
    assert r.exit_code == 0

    listing = runner.invoke(app, ["credentials", "list"])

    assert listing.exit_code == 0
    lines = listing.output.strip().splitlines()
    assert any("default" in ln and "${MY_CI_TOKEN} (set)" in ln for ln in lines)
    assert any("ci2" in ln and "${MY_LAPTOP_TOKEN} (not set)" in ln for ln in lines)
    assert any("typed" in ln and "stored token" in ln for ln in lines)
    # The values themselves never appear.
    assert "kyno_secret-value" not in listing.output
    assert "typed-secret" not in listing.output


def test_given_a_referenced_variable_set_to_an_empty_string_when_listing_then_it_reads_not_set(
    monkeypatch,
):
    # An empty variable cannot authenticate anything, so the listing treats
    # it the same as an absent one.
    monkeypatch.setenv("MY_EMPTY_TOKEN", "")
    added = runner.invoke(app, ["credentials", "add", "--token-env", "MY_EMPTY_TOKEN"])
    assert added.exit_code == 0

    listing = runner.invoke(app, ["credentials", "list"])

    assert listing.exit_code == 0
    assert "${MY_EMPTY_TOKEN} (not set)" in listing.output


def test_given_no_remote_flag_when_asking_whoami_then_it_refuses_naming_the_flag(tmp_path):
    result = runner.invoke(app, ["whoami"])

    assert result.exit_code == 1
    assert "--remote" in result.output


def test_given_a_checked_token_when_asking_whoami_remotely_then_its_name_and_scope_print(
    fake_dial,
):
    fake_dial.token = Token(id=7, name="ci", scope="write", created_at=datetime.now(UTC))

    result = runner.invoke(app, ["whoami", "--remote"])

    assert result.exit_code == 0
    assert result.output.strip() == "ci  write"
    assert fake_dial.closed


def test_given_a_server_that_checked_no_token_when_asking_whoami_remotely_then_it_says_so(
    fake_dial,
):
    result = runner.invoke(app, ["whoami", "--remote"])

    assert result.exit_code == 0, result.output
    assert "without checking for one" in result.output
    assert fake_dial.closed
