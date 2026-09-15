"""The workspace: what `kyno new` writes, and how config/server reads."""

import pytest
from typer.testing import CliRunner

from kyno.cli import app
from kyno.delivery import DeliverySettings, RecordingPolicy
from kyno.errors import ConfigError
from kyno.public_page import PageConfig
from kyno.server_config import Settings
from kyno.workspace import create_workspace, find_workspace, read_config

runner = CliRunner()


def make(tmp_path, name="acme"):
    return create_workspace(tmp_path / name)


def write_config(root, body):
    (root / "config" / "server").write_text(body, encoding="utf-8")


def test_given_a_new_workspace_when_listing_it_then_the_four_files_are_there(tmp_path):
    root = make(tmp_path)
    files = sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())
    assert files == [".gitignore", "README.md", "config/server", "db/.keep"]


@pytest.mark.parametrize("body", ["", "[delivery]\nrecording_policy = always\n"])
def test_given_no_recording_timeout_when_loading_settings_then_it_defaults_to_one_second(
    tmp_path, monkeypatch, body
):
    root = make(tmp_path)
    write_config(root, body)
    monkeypatch.chdir(root)
    assert Settings.load().delivery.recording_timeout_seconds == 1.0


@pytest.mark.parametrize(
    "value, expected_seconds", [("0.25", 0.25), ("2", 2.0), ("${ACME_RECORDING_TIMEOUT}", 0.25)]
)
@pytest.mark.parametrize("policy", [pytest.param(None, id="default-policy"), "never", "always"])
def test_given_recording_policy_and_timeout_when_loading_settings_then_both_are_preserved(
    tmp_path, monkeypatch, value, expected_seconds, policy
):
    root = make(tmp_path)
    monkeypatch.setenv("ACME_RECORDING_TIMEOUT", "0.25")
    body = f"[delivery]\nrecording_timeout_seconds = {value}\n"
    if policy is not None:
        body += f"recording_policy = {policy}\n"
    write_config(root, body)
    monkeypatch.chdir(root)
    settings = Settings.load().delivery
    assert settings.recording_timeout_seconds == expected_seconds
    assert settings.recording_policy is RecordingPolicy(policy or "never")


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "-inf", "1e999", "true", "", "secret"])
@pytest.mark.parametrize("policy", ["never", "always"])
def test_given_invalid_timeout_when_reading_config_then_error_requires_positive_finite_seconds(
    tmp_path, value, policy
):
    root = make(tmp_path)
    write_config(
        root, f"[delivery]\nrecording_policy = {policy}\nrecording_timeout_seconds = {value}\n"
    )
    with pytest.raises(
        ConfigError, match="delivery.recording_timeout_seconds must be a positive finite number"
    ):
        read_config(root)


@pytest.mark.parametrize("value", [None, "", "nan"])
def test_given_invalid_timeout_reference_when_reading_config_then_configuration_is_rejected(
    tmp_path, monkeypatch, value
):
    root = make(tmp_path)
    write_config(root, "[delivery]\nrecording_timeout_seconds = ${ACME_RECORDING_TIMEOUT}\n")
    if value is None:
        monkeypatch.delenv("ACME_RECORDING_TIMEOUT", raising=False)
    else:
        monkeypatch.setenv("ACME_RECORDING_TIMEOUT", value)
    with pytest.raises(ConfigError, match="delivery.recording_timeout_seconds"):
        read_config(root)


@pytest.mark.parametrize("body", ["", "[server]\nhost = localhost\n", "[delivery]\n"])
def test_given_no_recording_policy_when_reading_then_it_defaults_to_never(tmp_path, body):
    root = make(tmp_path)
    write_config(root, body)
    assert read_config(root).delivery.recording_policy == "never"


@pytest.mark.parametrize("policy", ["never", "always"])
def test_given_a_recording_policy_when_reading_then_it_returns_the_enum(tmp_path, policy):
    root = make(tmp_path)
    write_config(root, f"[delivery]\nrecording_policy = {policy}\n")
    config = read_config(root)
    assert config.delivery.recording_policy is RecordingPolicy(policy)


@pytest.mark.parametrize("policy", ["sometimes", "ALWAYS", "true", ""])
def test_given_an_invalid_recording_policy_when_reading_then_it_names_the_choices(tmp_path, policy):
    root = make(tmp_path)
    write_config(root, f"[delivery]\nrecording_policy = {policy}\n")
    with pytest.raises(ConfigError, match="delivery.recording_policy must be never or always"):
        read_config(root)


@pytest.mark.parametrize("policy", ["never", "always"])
def test_given_a_recording_policy_reference_when_reading_then_it_resolves(
    tmp_path, monkeypatch, policy
):
    root = make(tmp_path)
    write_config(root, "[delivery]\nrecording_policy = ${ACME_RECORDING_POLICY}\n")
    monkeypatch.setenv("ACME_RECORDING_POLICY", policy)
    assert read_config(root).delivery.recording_policy == policy


def test_given_an_invalid_recording_policy_reference_when_reading_then_it_is_refused(
    tmp_path, monkeypatch
):
    root = make(tmp_path)
    write_config(root, "[delivery]\nrecording_policy = ${ACME_RECORDING_POLICY}\n")
    monkeypatch.setenv("ACME_RECORDING_POLICY", "sometimes")
    with pytest.raises(ConfigError, match="delivery.recording_policy must be never or always"):
        read_config(root)


def test_given_an_unset_recording_policy_reference_when_reading_then_it_names_the_variable(
    tmp_path, monkeypatch
):
    root = make(tmp_path)
    write_config(root, "[delivery]\nrecording_policy = ${ACME_RECORDING_POLICY}\n")
    monkeypatch.delenv("ACME_RECORDING_POLICY", raising=False)
    with pytest.raises(
        ConfigError,
        match=r"delivery.recording_policy reads \$\{ACME_RECORDING_POLICY\}, which is not set",
    ):
        read_config(root)


@pytest.mark.parametrize("policy", [None, "never", "always"])
def test_given_a_workspace_recording_policy_when_loading_settings_then_it_is_preserved(
    tmp_path, monkeypatch, policy
):
    root = make(tmp_path)
    if policy is not None:
        write_config(root, f"[delivery]\nrecording_policy = {policy}\n")
    monkeypatch.chdir(root)
    assert Settings.load().delivery.recording_policy == (policy or "never")


@pytest.mark.parametrize("key", ["retention", "policy", "recording_polcy"])
def test_given_unknown_delivery_key_when_reading_then_the_key_is_rejected(tmp_path, key):
    root = make(tmp_path)
    write_config(root, f"[delivery]\n{key} = never\n")
    with pytest.raises(ConfigError, match=rf"unknown key '{key}' in \[delivery\]"):
        read_config(root)


def test_given_blank_policy_reference_when_reading_then_the_error_names_delivery(
    tmp_path, monkeypatch
):
    root = make(tmp_path)
    write_config(root, "[delivery]\nrecording_policy = ${ACME_RECORDING_POLICY}\n")
    monkeypatch.setenv("ACME_RECORDING_POLICY", " ")
    with pytest.raises(
        ConfigError,
        match=(
            r"delivery.recording_policy reads \$\{ACME_RECORDING_POLICY\}, which is set but blank"
        ),
    ):
        read_config(root)


def test_given_explicit_delivery_settings_when_constructing_then_other_defaults_stay_never():
    enabled = Settings(
        "sqlite://", "localhost", 2256, PageConfig(), delivery=DeliverySettings("always")
    )
    default = Settings("sqlite://", "localhost", 2256, PageConfig())
    assert enabled.delivery.recording_policy is RecordingPolicy.ALWAYS
    assert default.delivery.recording_policy is RecordingPolicy.NEVER


def test_given_a_new_workspace_when_reading_its_config_then_sqlite_lives_under_db(tmp_path):
    root = make(tmp_path)
    config = read_config(root)
    assert config.database_url == f"sqlite:///{root / 'db' / 'kyno.sqlite3'}"
    assert config.host == "127.0.0.1" and config.port == 2256
    assert config.allow_insecure is False and config.page == {}


def test_given_an_existing_workspace_when_creating_again_then_it_is_refused(tmp_path):
    make(tmp_path)
    with pytest.raises(ConfigError, match="already a workspace"):
        make(tmp_path)


def test_given_a_subdirectory_when_finding_the_workspace_then_it_walks_up(tmp_path):
    root = make(tmp_path)
    below = root / "a" / "b"
    below.mkdir(parents=True)
    assert find_workspace(below) == root


def test_given_no_workspace_above_when_finding_then_there_is_none(tmp_path):
    assert find_workspace(tmp_path) is None


def test_given_a_reference_value_when_reading_then_the_environment_variable_supplies_it(
    tmp_path, monkeypatch
):
    root = make(tmp_path)
    write_config(root, "[server]\nport = ${ACME_PORT}\n")
    monkeypatch.setenv("ACME_PORT", "9001")
    assert read_config(root).port == 9001


def test_given_an_unset_reference_when_reading_then_the_error_names_the_variable(tmp_path):
    root = make(tmp_path)
    write_config(root, "[server]\nhost = ${ACME_HOST}\n")
    with pytest.raises(ConfigError, match=r"server.host reads \$\{ACME_HOST\}, which is not set"):
        read_config(root)


def test_given_a_blank_reference_when_reading_then_it_is_refused_not_empty(tmp_path, monkeypatch):
    root = make(tmp_path)
    write_config(root, "[database]\nurl = ${ACME_DB}\n")
    monkeypatch.setenv("ACME_DB", "   ")
    with pytest.raises(ConfigError, match="which is set but blank"):
        read_config(root)


def test_given_an_unknown_key_with_a_typo_when_reading_then_it_is_refused(tmp_path):
    root = make(tmp_path)
    write_config(root, "[server]\nhots = x\n")
    with pytest.raises(ConfigError, match="unknown key 'hots'"):
        read_config(root)


@pytest.mark.parametrize("section", ["serverr", "recordings"])
def test_given_an_unknown_section_when_reading_then_it_is_refused(tmp_path, section):
    root = make(tmp_path)
    write_config(root, f"[{section}]\npolicy = always\n")
    with pytest.raises(ConfigError, match=rf"unknown section \[{section}\]"):
        read_config(root)


def test_given_an_unknown_adapter_when_reading_then_the_choices_are_named(tmp_path):
    root = make(tmp_path)
    write_config(root, "[database]\nadapter = oracle\n")
    with pytest.raises(
        ConfigError, match="unknown adapter 'oracle': one of mysql, postgresql, sqlite3"
    ):
        read_config(root)


def test_given_url_beside_split_keys_when_reading_then_pick_one_is_refused(tmp_path):
    root = make(tmp_path)
    write_config(root, "[database]\nurl = sqlite://\nadapter = sqlite3\n")
    with pytest.raises(ConfigError, match="pick one"):
        read_config(root)


def test_given_split_postgres_keys_when_reading_then_the_url_is_assembled(tmp_path, monkeypatch):
    root = make(tmp_path)
    write_config(
        root,
        "[database]\nadapter = postgresql\nhost = db.internal\nport = 6432\n"
        "database = kyno\nusername = kyno\npassword = ${ACME_DB_PASSWORD}\n",
    )
    monkeypatch.setenv("ACME_DB_PASSWORD", "s3c@r:t/")
    url = read_config(root).database_url
    assert url == "postgresql+psycopg://kyno:s3c%40r%3At%2F@db.internal:6432/kyno"


def test_given_postgres_without_a_database_name_when_reading_then_it_is_refused(tmp_path):
    root = make(tmp_path)
    write_config(root, "[database]\nadapter = postgresql\nhost = db.internal\n")
    with pytest.raises(ConfigError, match="database.database is required"):
        read_config(root)


def test_given_a_relative_sqlite_path_when_reading_then_it_anchors_at_the_workspace(tmp_path):
    root = make(tmp_path)
    write_config(root, "[database]\nadapter = sqlite3\ndatabase = other/place.sqlite3\n")
    assert read_config(root).database_url == f"sqlite:///{root / 'other' / 'place.sqlite3'}"


def test_given_a_non_integer_port_when_reading_then_it_is_refused(tmp_path):
    root = make(tmp_path)
    write_config(root, "[server]\nport = abc\n")
    with pytest.raises(ConfigError, match="server.port must be an integer, got 'abc'"):
        read_config(root)


def test_given_a_password_when_printing_the_config_then_it_never_appears(tmp_path):
    root = make(tmp_path)
    write_config(
        root,
        "[database]\nadapter = postgresql\ndatabase = kyno\npassword = hunter2\nusername = u\n",
    )
    assert "hunter2" not in repr(read_config(root))


def test_given_page_keys_when_reading_then_they_come_back_resolved(tmp_path, monkeypatch):
    root = make(tmp_path)
    write_config(root, "[page]\naccent = ${ACME_ACCENT}\nbackground = #fff\n")
    monkeypatch.setenv("ACME_ACCENT", "#123456")
    assert read_config(root).page == {"accent": "#123456", "background": "#fff"}


def test_given_kyno_new_run_twice_then_the_first_creates_and_the_second_is_refused(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    first = runner.invoke(app, ["new", "acme"])
    assert first.exit_code == 0, first.output
    assert "created workspace 'acme'" in first.output
    assert (tmp_path / "acme" / "config" / "server").is_file()
    again = runner.invoke(app, ["new", "acme"])
    assert again.exit_code == 1
    assert "already a workspace" in again.output


def test_given_a_file_that_is_not_ini_when_reading_then_the_error_says_so(tmp_path):
    root = make(tmp_path)
    write_config(root, "not ini at all\n[")
    with pytest.raises(ConfigError, match="is not valid INI"):
        read_config(root)


def test_given_an_unreadable_config_when_reading_then_the_error_is_clean(tmp_path):
    import os

    if os.geteuid() == 0:
        pytest.skip("root ignores file permissions")
    root = make(tmp_path)
    (root / "config" / "server").chmod(0o000)
    try:
        with pytest.raises(ConfigError, match="cannot read"):
            read_config(root)
    finally:
        (root / "config" / "server").chmod(0o600)


def test_given_split_mysql_keys_when_reading_then_the_url_is_assembled(tmp_path, monkeypatch):
    root = make(tmp_path)
    write_config(
        root,
        "[database]\nadapter = mysql\nhost = db.internal\nport = 3306\n"
        "database = kyno\nusername = kyno\npassword = ${ACME_DB_PASSWORD}\n",
    )
    monkeypatch.setenv("ACME_DB_PASSWORD", "s3cret")
    url = read_config(root).database_url
    assert url == "mysql+pymysql://kyno:s3cret@db.internal:3306/kyno"


def test_given_mysql_without_a_database_name_when_reading_then_it_is_refused(tmp_path):
    root = make(tmp_path)
    write_config(root, "[database]\nadapter = mysql\nhost = db.internal\n")
    with pytest.raises(ConfigError, match="database.database is required for mysql"):
        read_config(root)


def test_given_only_host_and_database_when_assembling_then_defaults_fill_the_rest(tmp_path):
    root = make(tmp_path)
    write_config(root, "[database]\nadapter = mysql\nhost = db.internal\ndatabase = kyno\n")
    assert read_config(root).database_url == "mysql+pymysql://db.internal/kyno"


def test_given_a_username_without_a_password_when_assembling_then_the_url_has_no_password(tmp_path):
    root = make(tmp_path)
    write_config(
        root,
        "[database]\nadapter = postgresql\nhost = db.internal\ndatabase = kyno\nusername = kyno\n",
    )
    assert read_config(root).database_url == "postgresql+psycopg://kyno@db.internal/kyno"
