"""The two files behind remote mode, and the commands that own them."""

import pathlib
import re
import stat

import pytest
from typer.testing import CliRunner

from kyno.cli import app
from kyno.profiles import (
    ProfileError,
    add_credentials,
    add_remote,
    config_dir,
    credentials,
    credentials_path,
    remotes,
    remotes_path,
    resolve,
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
    assert remotes_path() == home / ".kyno" / "remotes"
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


def test_given_no_credentials_when_adding_a_remote_then_it_is_refused_naming_the_fix():
    with pytest.raises(ProfileError) as refused:
        add_remote("https://kyno.mybiz.com")
    assert "no credentials profile 'default'; you have: none" in str(refused.value)
    assert str(refused.value).endswith("Create it with: kyno credentials add")
    assert not remotes_path().exists()


def test_given_default_credentials_when_adding_a_remote_then_it_points_at_them():
    add_credentials(token_env="KYNO_TOKEN")
    assert add_remote("https://kyno.mybiz.com/") == "added"
    remote = remotes()["default"]
    assert remote.url == "https://kyno.mybiz.com" and remote.credentials == "default"
    assert remote.token_env is None and remote.source == "credentials 'default'"


def test_given_a_named_credential_when_adding_a_remote_then_the_pointer_is_that_name():
    add_credentials("oncall", token_env="KYNO_ONCALL_TOKEN")
    add_remote("https://kyno.mybiz.com", "oncall", credentials_profile="oncall")
    assert remotes()["oncall"].credentials == "oncall"


def test_given_a_missing_named_credential_when_adding_a_remote_then_the_listing_says_what_exists():
    add_credentials("default", token_env="KYNO_TOKEN")
    with pytest.raises(ProfileError, match="no credentials profile 'oncall'; you have: default"):
        add_remote("https://kyno.mybiz.com", "oncall", credentials_profile="oncall")


def test_given_a_token_env_when_adding_a_remote_then_no_credentials_are_needed():
    add_remote("https://kyno.mybiz.com", "ci", token_env="KYNO_TOKEN")
    remote = remotes()["ci"]
    assert remote.token_env == "KYNO_TOKEN" and remote.credentials is None
    assert (
        remotes_path().read_text()
        == "[ci]\nurl = https://kyno.mybiz.com\ntoken = ${KYNO_TOKEN}\n\n"
    )


def test_given_both_sources_when_adding_a_remote_then_it_is_refused():
    add_credentials(token_env="KYNO_TOKEN")
    with pytest.raises(ProfileError, match="one way"):
        add_remote("https://kyno.mybiz.com", credentials_profile="default", token_env="X")


@pytest.mark.parametrize(
    "url",
    [
        "kyno.mybiz.com",
        "https://",
        "ftp://kyno.mybiz.com",
        "https:///path",
        "https://user:pw@kyno.mybiz.com",
        "https://kyno.mybiz.com?x=1",
        "https://kyno.mybiz.com#top",
        "https://kyno .mybiz.com",
        "https://-kyno.mybiz.com",
    ],
)
def test_given_a_bad_url_when_adding_a_remote_then_it_is_refused(url):
    with pytest.raises(ProfileError, match="not a server URL"):
        add_remote(url, token_env="X")


@pytest.mark.parametrize(
    "url", ["http://localhost:8080", "https://kyno.mybiz.com/base/path", "https://10.0.0.7:8443"]
)
def test_given_a_dialable_url_when_adding_a_remote_then_it_is_accepted(url):
    add_remote(url, "p", token_env="X")
    assert remotes()["p"].url == url.rstrip("/")


def test_given_an_existing_profile_when_adding_a_remote_again_then_it_is_replaced():
    add_remote("https://old.mybiz.com", "pdx", token_env="A")
    assert add_remote("https://pdx.mybiz.com", "pdx", token_env="B") == "updated"
    assert remotes()["pdx"].url == "https://pdx.mybiz.com" and len(remotes()) == 1


def test_given_several_profiles_when_sharing_one_credential_then_each_keeps_its_own_url():
    add_credentials("ops", token_env="OPS_TOKEN")
    for region in ("pdx", "scl", "cdg"):
        add_remote(f"https://{region}.mybiz.com", region, credentials_profile="ops")
    assert {r.credentials for r in remotes().values()} == {"ops"}
    assert remotes()["scl"].url == "https://scl.mybiz.com"


def test_given_a_profile_on_env_credentials_when_resolving_then_the_chain_ends_at_the_value(
    monkeypatch,
):
    add_credentials("oncall", token_env="KYNO_ONCALL_TOKEN")
    add_remote("https://kyno.mybiz.com", "oncall", credentials_profile="oncall")
    monkeypatch.setenv("KYNO_ONCALL_TOKEN", "t0k")
    got = resolve("oncall")
    assert (got.url, got.token) == ("https://kyno.mybiz.com", "t0k")
    assert (
        got.chain
        == "oncall -> https://kyno.mybiz.com -> credentials 'oncall' -> ${KYNO_ONCALL_TOKEN}"
    )
    assert "t0k" not in repr(got)


def test_given_a_profile_on_a_written_token_when_resolving_then_that_token_is_used():
    add_credentials(token="s3cret")
    add_remote("https://kyno.mybiz.com")
    got = resolve()
    assert (
        got.token == "s3cret"
        and got.chain == "default -> https://kyno.mybiz.com -> credentials 'default'"
    )


def test_given_a_profile_on_a_token_env_when_resolving_then_the_variable_is_read(monkeypatch):
    add_remote("https://kyno.mybiz.com", "ci", token_env="KYNO_TOKEN")
    monkeypatch.setenv("KYNO_TOKEN", "ci-token")
    assert resolve("ci").token == "ci-token"


def test_given_an_unset_variable_when_resolving_then_it_fails_loud_naming_the_variable(monkeypatch):
    add_remote("https://kyno.mybiz.com", "ci", token_env="KYNO_TOKEN")
    monkeypatch.delenv("KYNO_TOKEN", raising=False)
    with pytest.raises(
        ProfileError,
        match=r"remote profile 'ci' reads its token from \$\{KYNO_TOKEN\}, which is not set",
    ):
        resolve("ci")


def test_given_a_blank_variable_when_resolving_then_it_is_refused_not_empty(monkeypatch):
    add_credentials(token_env="KYNO_TOKEN")
    add_remote("https://kyno.mybiz.com")
    monkeypatch.setenv("KYNO_TOKEN", "  ")
    with pytest.raises(ProfileError, match="set but blank"):
        resolve()


def test_given_an_unknown_profile_when_resolving_then_the_error_names_what_exists_and_the_fix():
    add_remote("https://pdx.mybiz.com", "pdx", token_env="A")
    with pytest.raises(ProfileError) as refused:
        resolve("prod")
    assert "no remote profile 'prod'; you have: pdx" in str(refused.value)
    assert "kyno remote add --url URL --profile prod" in str(refused.value)


def test_given_a_remote_whose_credentials_vanished_when_resolving_then_it_says_so():
    add_credentials("oncall", token_env="X")
    add_remote("https://kyno.mybiz.com", "oncall", credentials_profile="oncall")
    credentials_path().unlink()
    with pytest.raises(
        ProfileError, match="points at credentials 'oncall', which do not exist; you have: none"
    ):
        resolve("oncall")


def test_given_a_per_run_credential_when_resolving_then_it_swaps_the_source_and_leaves_the_files(
    monkeypatch,
):
    add_credentials("default", token_env="READ_TOKEN")
    add_credentials("oncall", token_env="WRITE_TOKEN")
    add_remote("https://kyno.mybiz.com")
    monkeypatch.setenv("READ_TOKEN", "r")
    monkeypatch.setenv("WRITE_TOKEN", "w")
    before = remotes_path().read_text()
    got = resolve(credentials_profile="oncall")
    assert got.token == "w" and got.chain.endswith(
        "credentials 'oncall' -> ${WRITE_TOKEN} (this run)"
    )
    assert remotes_path().read_text() == before and remotes()["default"].credentials == "default"


def test_given_a_per_run_token_env_when_resolving_then_that_variable_is_read(monkeypatch):
    add_credentials(token_env="READ_TOKEN")
    add_remote("https://kyno.mybiz.com")
    monkeypatch.setenv("ONE_OFF", "o")
    assert resolve(token_env="ONE_OFF").token == "o"


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


def test_given_credentials_when_running_remote_add_then_it_says_the_bundle_and_where():
    runner.invoke(app, ["credentials", "add", "--token-env", "KYNO_TOKEN"])
    r = runner.invoke(app, ["remote", "add", "--url", "https://kyno.mybiz.com/"])
    assert r.exit_code == 0, r.output
    assert (
        "added remote profile 'default': https://kyno.mybiz.com, token from credentials 'default'"
        in r.output
    )
    assert str(remotes_path()) in r.output


def test_given_no_credentials_when_running_remote_add_then_the_error_names_have_and_fix():
    r = runner.invoke(app, ["remote", "add", "--url", "https://kyno.mybiz.com", "--profile", "pdx"])
    assert r.exit_code == 1
    assert "error: no credentials profile 'default'; you have: none" in plain(r.output)
    assert "Create it with: kyno credentials add" in plain(r.output)
    assert "--profile default" not in plain(r.output)


def test_given_a_token_env_when_running_remote_add_then_no_credentials_file_is_touched():
    r = runner.invoke(
        app,
        [
            "remote",
            "add",
            "--url",
            "https://ci.mybiz.com",
            "--profile",
            "ci",
            "--token-env",
            "KYNO_TOKEN",
        ],
    )
    assert r.exit_code == 0, r.output
    assert "token from ${KYNO_TOKEN}" in r.output
    assert not credentials_path().exists() and remotes()["ci"].token_env == "KYNO_TOKEN"


def test_given_a_positional_name_when_running_remote_add_then_it_is_not_accepted():
    # Nothing like `prod` is a keyword; profiles are named with --profile only.
    r = runner.invoke(
        app, ["remote", "add", "prod", "--url", "https://kyno.mybiz.com", "--token-env", "X"]
    )
    assert r.exit_code != 0


def test_given_nothing_configured_when_resolving_default_then_the_fix_needs_no_profile_flag():
    with pytest.raises(ProfileError) as refused:
        resolve()
    assert str(refused.value).endswith("Create it with: kyno remote add --url URL")
