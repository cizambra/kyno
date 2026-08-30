"""The credentials file behind remote mode, and the command that owns it."""

import pathlib
import re
import stat

import pytest
from typer.testing import CliRunner

from kyno.cli import app
from kyno.profiles import (
    ProfileError,
    add_credentials,
    config_dir,
    credentials,
    credentials_path,
)

runner = CliRunner()


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    """A scratch home directory, so ~/.kyno is never the real one."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    (tmp_path / "work").mkdir()
    monkeypatch.chdir(tmp_path / "work")
    return tmp_path


def plain(output):
    return " ".join(re.sub(r"\x1b\[[0-9;]*m", "", output).split())


def test_given_any_home_when_locating_the_files_then_they_are_in_dot_kyno_never_cwd(home):
    assert config_dir() == home / ".kyno"
    assert credentials_path() == home / ".kyno" / "credentials"
    add_credentials("default", token_env="KYNO_TOKEN")
    assert credentials_path().exists() and not list(pathlib.Path.cwd().glob("*"))


def test_given_a_token_env_when_adding_credentials_then_the_file_holds_a_reference():
    assert add_credentials("oncall", token_env="KYNO_ONCALL_TOKEN") == "added"
    assert credentials_path().read_text() == "[oncall]\ntoken = ${KYNO_ONCALL_TOKEN}\n\n"
    assert credentials()["oncall"].env_var == "KYNO_ONCALL_TOKEN"


def test_given_a_token_when_adding_credentials_then_it_is_written_in():
    add_credentials(token="s3cret")
    assert credentials()["default"].token == "s3cret" and credentials()["default"].env_var is None


@pytest.mark.parametrize("source", [{"token": "s3cret"}, {"token_env": "KYNO_TOKEN"}])
def test_given_any_add_when_the_credentials_file_is_written_then_it_is_owner_readable_only(source):
    add_credentials(**source)
    assert stat.S_IMODE(credentials_path().stat().st_mode) == 0o600


def test_given_both_or_neither_source_when_adding_credentials_then_it_is_refused():
    with pytest.raises(ProfileError, match="one way"):
        add_credentials(token="x", token_env="X")
    with pytest.raises(ProfileError, match="one way"):
        add_credentials()
    assert not credentials_path().exists()


def test_given_a_blank_token_when_adding_credentials_then_nothing_is_written():
    with pytest.raises(ProfileError, match="blank"):
        add_credentials(token="   ")
    assert not credentials_path().exists()


def test_given_an_existing_profile_when_adding_credentials_again_then_it_is_replaced():
    add_credentials("default", token_env="OLD")
    assert add_credentials("default", token_env="NEW") == "updated"
    assert credentials()["default"].env_var == "NEW" and len(credentials()) == 1


def test_given_a_bad_name_when_adding_credentials_then_it_is_refused():
    with pytest.raises(ProfileError, match="not a profile name"):
        add_credentials("on call", token_env="X")
    with pytest.raises(ProfileError, match="not an environment variable name"):
        add_credentials("ok", token_env="not-a-var")


def test_given_the_repr_of_a_credential_when_printed_then_the_token_is_not_in_it():
    add_credentials(token="s3cret")
    assert "s3cret" not in repr(credentials()["default"])


def test_given_token_env_when_running_credentials_add_then_it_says_what_it_wrote_and_where():
    r = runner.invoke(
        app, ["credentials", "add", "--profile", "oncall", "--token-env", "KYNO_ONCALL"]
    )
    assert r.exit_code == 0, r.output
    assert "added credentials profile 'oncall': ${KYNO_ONCALL}" in r.output
    assert str(credentials_path()) in r.output and "owner-readable only" in r.output


def test_given_no_token_env_when_running_credentials_add_then_the_token_is_prompted_hidden():
    r = runner.invoke(app, ["credentials", "add"], input="s3cret\n")
    assert r.exit_code == 0, r.output
    assert "s3cret" not in r.output
    assert credentials()["default"].token == "s3cret"


def test_given_a_blank_prompt_when_running_credentials_add_then_it_is_refused():
    r = runner.invoke(app, ["credentials", "add"], input="   \n")
    assert r.exit_code == 1
    assert "blank" in r.output and not credentials_path().exists()


def test_given_a_token_flag_when_running_credentials_add_then_it_is_rejected_as_unknown():
    # Tokens never travel on a command line: shell history and process lists.
    r = runner.invoke(app, ["credentials", "add", "--token", "s3cret"])
    assert r.exit_code != 0 and "no such option" in plain(r.output).lower()
