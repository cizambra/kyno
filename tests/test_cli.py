import json

import pytest
from typer.testing import CliRunner

from kyno.cli import app

runner = CliRunner()


def apply_yaml(
    tmp_path, *, mission, principles=(), constitution=None, note=None, by=None, name="applied.yaml"
):
    """Write a constitution file and apply it: the only way content lands."""
    lines = []
    if constitution is not None:
        lines.append(f"constitution: {constitution}")
    lines.append(f"mission: {mission}")
    if principles:
        lines.append("principles:")
        lines.extend(f"  - {p}" for p in principles)
    path = tmp_path / name
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    args = ["set", str(path)]
    if note is not None:
        args += ["--note", note]
    if by is not None:
        args += ["--by", by]
    return runner.invoke(app, args)


def test_given_an_applied_file_when_reading_current_then_that_content_is_served(
    tmp_path, monkeypatch
):
    """The whole loop in one breath: init the store, apply a file, and
    `kyno current` serves exactly that content."""
    monkeypatch.setenv("KYNO_DATABASE_URL", f"sqlite:///{tmp_path / 'c.sqlite3'}")
    assert runner.invoke(app, ["init-db"]).exit_code == 0
    r = apply_yaml(tmp_path, mission="M1", principles=["p1"], note="init")
    assert r.exit_code == 0
    out = runner.invoke(app, ["current"])
    assert out.exit_code == 0
    payload = json.loads(out.stdout)
    assert payload["mission"] == "M1"
    assert payload["principles"] == [{"title": "p1", "description": ""}]


def test_given_no_note_when_applying_then_the_apply_is_refused(tmp_path, monkeypatch):
    """Notes are not optional: every applied version answers "what
    changed?", so an apply without --note is refused. (--dry-run is the
    one exception, tested with the dry-run behavior.)"""
    monkeypatch.setenv("KYNO_DATABASE_URL", f"sqlite:///{tmp_path / 'c.sqlite3'}")
    runner.invoke(app, ["init-db"])
    r = apply_yaml(tmp_path, mission="M1")
    assert r.exit_code != 0


def test_current_against_uninitialized_db_reports_clean_error(tmp_path, monkeypatch):
    # No init-db here: the store raises sqlalchemy.exc.OperationalError,
    # not a kyno CoherenceError -- both must still surface as a clean CLI error.
    monkeypatch.setenv("KYNO_DATABASE_URL", f"sqlite:///{tmp_path / 'never_init.sqlite3'}")
    r = runner.invoke(app, ["current"])
    assert r.exit_code == 1
    assert "error:" in r.output.lower()
    assert "Traceback" not in r.output


def test_set_against_uninitialized_db_reports_clean_error(tmp_path, monkeypatch):
    monkeypatch.setenv("KYNO_DATABASE_URL", f"sqlite:///{tmp_path / 'never_init.sqlite3'}")
    r = apply_yaml(tmp_path, mission="M1", note="init")
    assert r.exit_code == 1
    assert "error:" in r.output.lower()
    assert "Traceback" not in r.output


def test_current_on_initialized_but_empty_store_reports_no_constitution_set(tmp_path, monkeypatch):
    monkeypatch.setenv("KYNO_DATABASE_URL", f"sqlite:///{tmp_path / 'c.sqlite3'}")
    runner.invoke(app, ["init-db"])
    r = runner.invoke(app, ["current"])
    assert r.exit_code == 0
    assert "version 0" in r.output
    assert "error:" not in r.output.lower()


def test_given_a_by_flag_when_applying_then_the_author_is_recorded(tmp_path, monkeypatch):
    monkeypatch.setenv("KYNO_DATABASE_URL", f"sqlite:///{tmp_path / 'c.sqlite3'}")
    runner.invoke(app, ["init-db"])
    r = apply_yaml(tmp_path, mission="M1", principles=["p1"], note="init", by="alice")
    assert r.exit_code == 0
    out = runner.invoke(app, ["current"])
    assert out.exit_code == 0
    payload = json.loads(out.stdout)
    assert payload["created_by"] == "alice"


def test_serve_reports_invalid_port_as_clean_error(monkeypatch, tmp_path):
    monkeypatch.setenv("KYNO_DATABASE_URL", f"sqlite:///{tmp_path / 'c.sqlite3'}")
    monkeypatch.setenv("KYNO_PORT", "abc")
    r = runner.invoke(app, ["serve", "--transport", "http"])
    assert r.exit_code == 1
    assert "error:" in r.output.lower()
    assert "Traceback" not in r.output


def test_serve_http_refuses_without_token(monkeypatch, tmp_path):
    monkeypatch.setenv("KYNO_DATABASE_URL", f"sqlite:///{tmp_path / 'c.sqlite3'}")
    monkeypatch.delenv("KYNO_TOKEN", raising=False)
    monkeypatch.delenv("KYNO_ALLOW_INSECURE_HTTP", raising=False)
    r = runner.invoke(app, ["serve", "--transport", "http"])
    assert r.exit_code != 0
    assert "token" in r.output.lower()


def test_serve_http_allows_insecure_optin(monkeypatch, tmp_path):
    monkeypatch.setenv("KYNO_DATABASE_URL", f"sqlite:///{tmp_path / 'c.sqlite3'}")
    monkeypatch.delenv("KYNO_TOKEN", raising=False)
    monkeypatch.setenv("KYNO_ALLOW_INSECURE_HTTP", "1")
    import uvicorn

    ran = {}
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: ran.setdefault("ran", True))
    runner.invoke(app, ["serve", "--transport", "http"])
    assert ran.get("ran") is True


@pytest.mark.parametrize("value", ["TRUE", "true", "1"])
def test_serve_http_insecure_optin_is_case_insensitive_and_shows_warning(
    monkeypatch, tmp_path, value
):
    monkeypatch.setenv("KYNO_DATABASE_URL", f"sqlite:///{tmp_path / 'c.sqlite3'}")
    monkeypatch.delenv("KYNO_TOKEN", raising=False)
    monkeypatch.setenv("KYNO_ALLOW_INSECURE_HTTP", value)
    import uvicorn

    ran = {}
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: ran.setdefault("ran", True))
    r = runner.invoke(app, ["serve", "--transport", "http"])
    assert ran.get("ran") is True
    assert "WARNING" in r.output
    assert "KYNO_TOKEN" in r.output


@pytest.mark.parametrize("value", ["yes", "0"])
def test_serve_http_insecure_optin_refuses_non_matching_values(monkeypatch, tmp_path, value):
    monkeypatch.setenv("KYNO_DATABASE_URL", f"sqlite:///{tmp_path / 'c.sqlite3'}")
    monkeypatch.delenv("KYNO_TOKEN", raising=False)
    monkeypatch.setenv("KYNO_ALLOW_INSECURE_HTTP", value)
    r = runner.invoke(app, ["serve", "--transport", "http"])
    assert r.exit_code != 0
    assert "token" in r.output.lower()


def test_export_round_trips_written_versions(tmp_path, monkeypatch):
    monkeypatch.setenv("KYNO_DATABASE_URL", f"sqlite:///{tmp_path / 'c.sqlite3'}")
    runner.invoke(app, ["init-db"])
    apply_yaml(tmp_path, mission="M1", note="v1")
    apply_yaml(tmp_path, mission="M2", note="v2")
    apply_yaml(tmp_path, mission="M3", note="v3")

    full = runner.invoke(app, ["export"])
    assert full.exit_code == 0
    rows = json.loads(full.stdout)
    assert len(rows) == 3
    assert [r["version"] for r in rows] == [1, 2, 3]
    assert rows[1]["mission"] == "M2" and rows[1]["change_note"] == "v2"

    partial = runner.invoke(app, ["export", "--from", "2"])
    assert partial.exit_code == 0
    partial_rows = json.loads(partial.stdout)
    assert len(partial_rows) == 2
    assert [r["version"] for r in partial_rows] == [2, 3]


def test_export_on_empty_store_prints_empty_json_array(tmp_path, monkeypatch):
    monkeypatch.setenv("KYNO_DATABASE_URL", f"sqlite:///{tmp_path / 'c.sqlite3'}")
    runner.invoke(app, ["init-db"])
    r = runner.invoke(app, ["export"])
    assert r.exit_code == 0
    assert json.loads(r.stdout) == []


def test_export_against_uninitialized_db_reports_clean_error(tmp_path, monkeypatch):
    monkeypatch.setenv("KYNO_DATABASE_URL", f"sqlite:///{tmp_path / 'never_init.sqlite3'}")
    r = runner.invoke(app, ["export"])
    assert r.exit_code == 1
    assert "error:" in r.output.lower()
    assert "Traceback" not in r.output


def test_serve_bogus_transport_is_argparse_style_exit_2(monkeypatch, tmp_path):
    monkeypatch.setenv("KYNO_DATABASE_URL", f"sqlite:///{tmp_path / 'c.sqlite3'}")
    r = runner.invoke(app, ["serve", "--transport", "bogus"])
    assert r.exit_code == 2


def test_constitution_flag_round_trips_a_named_constitution(tmp_path, monkeypatch):
    monkeypatch.setenv("KYNO_DATABASE_URL", f"sqlite:///{tmp_path / 'c.sqlite3'}")
    runner.invoke(app, ["init-db"])
    r = apply_yaml(tmp_path, mission="EU1", principles=["p1"], constitution="eu", note="init")
    assert r.exit_code == 0
    out = runner.invoke(app, ["current", "--constitution", "eu"])
    assert json.loads(out.stdout)["mission"] == "EU1"
    assert "version 0" in runner.invoke(app, ["current"]).output


def test_named_and_default_constitutions_keep_independent_versions(tmp_path, monkeypatch):
    monkeypatch.setenv("KYNO_DATABASE_URL", f"sqlite:///{tmp_path / 'c.sqlite3'}")
    runner.invoke(app, ["init-db"])
    apply_yaml(tmp_path, mission="M1", note="init")
    apply_yaml(tmp_path, mission="EU1", constitution="eu", note="init")
    apply_yaml(tmp_path, mission="EU2", constitution="eu", note="pivot")

    assert json.loads(runner.invoke(app, ["current"]).stdout)["version"] == 1
    eu = json.loads(runner.invoke(app, ["current", "--constitution", "eu"]).stdout)
    assert eu["version"] == 2 and eu["mission"] == "EU2"

    rows = json.loads(runner.invoke(app, ["export", "--constitution", "eu"]).stdout)
    assert [r["version"] for r in rows] == [1, 2]
    assert len(json.loads(runner.invoke(app, ["export"]).stdout)) == 1


def test_reads_of_an_unknown_constitution_report_the_empty_state(tmp_path, monkeypatch):
    monkeypatch.setenv("KYNO_DATABASE_URL", f"sqlite:///{tmp_path / 'c.sqlite3'}")
    runner.invoke(app, ["init-db"])
    apply_yaml(tmp_path, mission="M1", note="init")
    r = runner.invoke(app, ["current", "--constitution", "never-written"])
    assert r.exit_code == 0 and "version 0" in r.output
    e = runner.invoke(app, ["export", "--constitution", "never-written"])
    assert e.exit_code == 0 and json.loads(e.stdout) == []


def test_publish_and_unpublish_report_what_changed(tmp_path, monkeypatch):
    monkeypatch.setenv("KYNO_DATABASE_URL", f"sqlite:///{tmp_path / 'c.sqlite3'}")
    runner.invoke(app, ["init-db"])
    apply_yaml(tmp_path, mission="M1", note="init")

    pub = runner.invoke(app, ["publish"])
    assert pub.exit_code == 0
    assert "published" in pub.output
    assert "default" in pub.output
    assert "/constitutions/default" in pub.output

    un = runner.invoke(app, ["unpublish"])
    assert un.exit_code == 0
    assert "unpublished" in un.output
    assert "default" in un.output


def test_publish_says_whether_history_is_public(tmp_path, monkeypatch):
    monkeypatch.setenv("KYNO_DATABASE_URL", f"sqlite:///{tmp_path / 'c.sqlite3'}")
    runner.invoke(app, ["init-db"])
    apply_yaml(tmp_path, mission="M1", note="init")

    quiet = runner.invoke(app, ["publish"])
    assert "history" in quiet.output.lower()
    assert "hidden" in quiet.output.lower()

    loud = runner.invoke(app, ["publish", "--with-history"])
    assert loud.exit_code == 0
    assert "history" in loud.output.lower()
    assert "public" in loud.output.lower()


def test_publish_defaults_to_the_default_constitution_and_honors_the_flag(tmp_path, monkeypatch):
    monkeypatch.setenv("KYNO_DATABASE_URL", f"sqlite:///{tmp_path / 'c.sqlite3'}")
    runner.invoke(app, ["init-db"])
    apply_yaml(tmp_path, mission="M1", note="init")
    apply_yaml(tmp_path, mission="EU1", constitution="eu", note="init")

    r = runner.invoke(app, ["publish", "--constitution", "eu"])
    assert r.exit_code == 0
    assert "/constitutions/eu" in r.output


def test_publishing_a_constitution_with_no_direction_is_a_clean_error(tmp_path, monkeypatch):
    monkeypatch.setenv("KYNO_DATABASE_URL", f"sqlite:///{tmp_path / 'c.sqlite3'}")
    runner.invoke(app, ["init-db"])
    r = runner.invoke(app, ["publish", "--constitution", "never-written"])
    assert r.exit_code == 1
    assert "error:" in r.output.lower()
    assert "Traceback" not in r.output


def test_unpublishing_an_unknown_constitution_is_a_clean_error(tmp_path, monkeypatch):
    # A typo here must not print success while the real page stays public.
    monkeypatch.setenv("KYNO_DATABASE_URL", f"sqlite:///{tmp_path / 'c.sqlite3'}")
    runner.invoke(app, ["init-db"])
    apply_yaml(tmp_path, mission="M1", note="init")
    r = runner.invoke(app, ["unpublish", "--constitution", "defualt"])
    assert r.exit_code == 1
    assert "error:" in r.output.lower()
    assert "Traceback" not in r.output


def test_publish_against_uninitialized_db_reports_clean_error(tmp_path, monkeypatch):
    monkeypatch.setenv("KYNO_DATABASE_URL", f"sqlite:///{tmp_path / 'never_init.sqlite3'}")
    r = runner.invoke(app, ["publish"])
    assert r.exit_code == 1
    assert "error:" in r.output.lower()
    assert "Traceback" not in r.output


def test_publishing_an_unroutable_name_is_a_clean_error(tmp_path, monkeypatch):
    monkeypatch.setenv("KYNO_DATABASE_URL", f"sqlite:///{tmp_path / 'c.sqlite3'}")
    runner.invoke(app, ["init-db"])
    apply_yaml(tmp_path, mission="M1", constitution="acme/eu", note="init")
    r = runner.invoke(app, ["publish", "--constitution", "acme/eu"])
    assert r.exit_code == 1
    assert "error:" in r.output.lower()
    assert "Traceback" not in r.output


def test_given_a_head_when_reading_current_yaml_then_it_prints_in_file_format(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("KYNO_DATABASE_URL", f"sqlite:///{tmp_path / 'c.sqlite3'}")
    runner.invoke(app, ["init-db"])
    apply_yaml(tmp_path, mission="M1", principles=["p1"], note="init", by="camilo")
    r = runner.invoke(app, ["current", "--yaml"])
    assert r.exit_code == 0
    assert "constitution: default" in r.stdout
    assert "mission: M1" in r.stdout
    # Content only: the note and author live in the store, not the output.
    assert "note:" not in r.stdout and "by:" not in r.stdout


def test_given_the_yaml_read_out_when_reapplied_then_nothing_changes(tmp_path, monkeypatch):
    monkeypatch.setenv("KYNO_DATABASE_URL", f"sqlite:///{tmp_path / 'c.sqlite3'}")
    runner.invoke(app, ["init-db"])
    apply_yaml(tmp_path, mission="M1", principles=["p1"], note="init")
    out = runner.invoke(app, ["current", "--yaml"]).stdout
    target = tmp_path / "recovered.yaml"
    target.write_text(out, encoding="utf-8")
    r = runner.invoke(app, ["set", str(target), "--note", "reapply"])
    assert r.exit_code == 0
    assert "no field changed" in r.output


def test_given_two_applies_when_reading_current_yaml_then_the_latest_head_prints(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("KYNO_DATABASE_URL", f"sqlite:///{tmp_path / 'c.sqlite3'}")
    runner.invoke(app, ["init-db"])
    apply_yaml(tmp_path, mission="the old mission", note="first")
    apply_yaml(tmp_path, mission="the hotfix mission", note="hotfix")
    out = runner.invoke(app, ["current", "--yaml"]).stdout
    assert "the hotfix mission" in out
    assert "the old mission" not in out


def test_given_an_empty_store_when_reading_current_yaml_then_it_errors(tmp_path, monkeypatch):
    monkeypatch.setenv("KYNO_DATABASE_URL", f"sqlite:///{tmp_path / 'c.sqlite3'}")
    runner.invoke(app, ["init-db"])
    r = runner.invoke(app, ["current", "--yaml"])
    assert r.exit_code == 1
    assert "nothing to read" in r.output


def test_given_a_named_constitution_when_reading_current_yaml_then_the_name_routes_a_reapply(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("KYNO_DATABASE_URL", f"sqlite:///{tmp_path / 'c.sqlite3'}")
    runner.invoke(app, ["init-db"])
    apply_yaml(tmp_path, mission="EU rules", constitution="eu", note="init")
    out = runner.invoke(app, ["current", "--yaml", "--constitution", "eu"]).stdout
    assert "constitution: eu" in out
    # The name in the output is enough to route a later apply back to eu.
    target = tmp_path / "eu.yaml"
    target.write_text(out, encoding="utf-8")
    r = runner.invoke(app, ["set", str(target), "--note", "reapply"])
    assert "no field changed" in r.output


def test_given_no_by_flag_when_applying_then_the_system_user_is_recorded(tmp_path, monkeypatch):
    import getpass

    monkeypatch.setenv("KYNO_DATABASE_URL", f"sqlite:///{tmp_path / 'c.sqlite3'}")
    runner.invoke(app, ["init-db"])
    r = apply_yaml(tmp_path, mission="M1", note="init")
    assert r.exit_code == 0
    assert json.loads(r.stdout)["created_by"] == getpass.getuser()


def test_given_typos_and_custom_keys_when_checking_then_the_report_lists_them_without_blocking(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("KYNO_DATABASE_URL", f"sqlite:///{tmp_path / 'c.sqlite3'}")
    target = tmp_path / "constitution.yaml"
    target.write_text("mission: M\nprincipals:\n  - p1\nnote: n\n", encoding="utf-8")
    r = runner.invoke(app, ["check", str(target)])
    assert r.exit_code == 0
    assert "kyno fields set: mission" in r.output
    assert "principles" in r.output
    assert "note, principals" in r.output


def test_given_an_unparseable_file_when_checking_then_it_errors(tmp_path, monkeypatch):
    monkeypatch.setenv("KYNO_DATABASE_URL", f"sqlite:///{tmp_path / 'c.sqlite3'}")
    target = tmp_path / "constitution.yaml"
    target.write_text("mission: [unclosed\n", encoding="utf-8")
    r = runner.invoke(app, ["check", str(target)])
    assert r.exit_code == 1
    assert "error:" in r.output


def test_given_custom_fields_when_applying_then_they_are_ignored(tmp_path, monkeypatch):
    monkeypatch.setenv("KYNO_DATABASE_URL", f"sqlite:///{tmp_path / 'c.sqlite3'}")
    runner.invoke(app, ["init-db"])
    target = tmp_path / "constitution.yaml"
    target.write_text("mission: M1\nnote: the file note\nteam: lending\n", encoding="utf-8")
    r = runner.invoke(app, ["set", str(target), "--note", "the real note"])
    assert r.exit_code == 0
    payload = json.loads(r.stdout)
    assert payload["change_note"] == "the real note"


def test_given_an_edit_when_applied_then_the_delta_is_printed(tmp_path, monkeypatch):
    monkeypatch.setenv("KYNO_DATABASE_URL", f"sqlite:///{tmp_path / 'c.sqlite3'}")
    runner.invoke(app, ["init-db"])
    apply_yaml(tmp_path, mission="M1", note="init")
    r = apply_yaml(tmp_path, mission="M2", note="pivot")
    assert r.exit_code == 0
    assert 'The mission was "M1" and is now "M2".' in r.output
    # stdout stays the version JSON, pipeable; the delta rides stderr.
    assert json.loads(r.stdout)["version"] == 2


def test_given_an_empty_store_when_applying_then_the_first_version_is_announced(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("KYNO_DATABASE_URL", f"sqlite:///{tmp_path / 'c.sqlite3'}")
    runner.invoke(app, ["init-db"])
    r = apply_yaml(tmp_path, mission="M1", note="init")
    assert "Creates 'default' at version 1." in r.output


def test_given_dry_run_when_applying_then_the_delta_prints_and_nothing_is_persisted(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("KYNO_DATABASE_URL", f"sqlite:///{tmp_path / 'c.sqlite3'}")
    runner.invoke(app, ["init-db"])
    apply_yaml(tmp_path, mission="M1", note="init")
    target = tmp_path / "next.yaml"
    target.write_text("mission: M2\n", encoding="utf-8")
    r = runner.invoke(app, ["set", str(target), "--dry-run"])
    assert r.exit_code == 0
    assert 'The mission was "M1" and is now "M2".' in r.output
    head = json.loads(runner.invoke(app, ["current"]).stdout)
    assert head["version"] == 1 and head["mission"] == "M1"


def test_given_identical_content_when_dry_running_then_it_says_no_field_changed(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("KYNO_DATABASE_URL", f"sqlite:///{tmp_path / 'c.sqlite3'}")
    runner.invoke(app, ["init-db"])
    apply_yaml(tmp_path, mission="M1", note="init", name="same.yaml")
    r = runner.invoke(app, ["set", str(tmp_path / "same.yaml"), "--dry-run"])
    assert r.exit_code == 0
    assert "no field changed" in r.output


def test_given_dry_run_when_no_note_is_passed_then_it_still_runs(tmp_path, monkeypatch):
    monkeypatch.setenv("KYNO_DATABASE_URL", f"sqlite:///{tmp_path / 'c.sqlite3'}")
    runner.invoke(app, ["init-db"])
    target = tmp_path / "next.yaml"
    target.write_text("mission: M1\n", encoding="utf-8")
    r = runner.invoke(app, ["set", str(target), "--dry-run"])
    assert r.exit_code == 0


def test_given_an_apply_when_reading_stdout_then_the_json_is_indented_for_people(
    tmp_path, monkeypatch
):
    """The JSON is read by people at a terminal as often as by scripts, and
    indentation costs a script nothing. `current` and `export` match."""
    monkeypatch.setenv("KYNO_DATABASE_URL", f"sqlite:///{tmp_path / 'c.sqlite3'}")
    runner.invoke(app, ["init-db"])
    applied = apply_yaml(tmp_path, mission="M1", principles=["p1"], note="init")
    current = runner.invoke(app, ["current"])
    for out in (applied.stdout, current.stdout):
        assert out.startswith("{\n  ")
        assert json.loads(out)["principles"][0]["title"] == "p1"


def test_given_identical_content_when_applying_then_nothing_is_written_and_the_exit_is_clean(
    tmp_path, monkeypatch
):
    """A duplicate apply is the normal case for a rerun, not a mistake: no
    version is written, stderr says so, and stdout is the head in force."""
    monkeypatch.setenv("KYNO_DATABASE_URL", f"sqlite:///{tmp_path / 'c.sqlite3'}")
    runner.invoke(app, ["init-db"])
    apply_yaml(tmp_path, mission="M1", note="init", name="same.yaml")
    r = runner.invoke(app, ["set", str(tmp_path / "same.yaml"), "--note", "again"])
    assert r.exit_code == 0
    assert "no field changed" in r.output
    assert json.loads(r.stdout)["version"] == 1
    assert json.loads(runner.invoke(app, ["current"]).stdout)["version"] == 1


def test_given_a_whitespace_note_when_applying_then_it_is_refused_as_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("KYNO_DATABASE_URL", f"sqlite:///{tmp_path / 'c.sqlite3'}")
    runner.invoke(app, ["init-db"])
    r = apply_yaml(tmp_path, mission="M1", note="   ")
    assert r.exit_code != 0
    assert "note" in r.output.lower()


def test_given_no_name_anywhere_when_applying_then_the_default_constitution_receives_it(
    tmp_path, monkeypatch
):
    """No --constitution flag and no constitution: key in the file: the
    service's own default takes the version, and no other name does."""
    monkeypatch.setenv("KYNO_DATABASE_URL", f"sqlite:///{tmp_path / 'c.sqlite3'}")
    runner.invoke(app, ["init-db"])
    assert apply_yaml(tmp_path, mission="M1", note="init").exit_code == 0
    assert (
        json.loads(runner.invoke(app, ["current", "--constitution", "default"]).stdout)["mission"]
        == "M1"
    )
    assert json.loads(runner.invoke(app, ["current"]).stdout)["version"] == 1
    assert "no constitution set" in runner.invoke(app, ["current", "--constitution", "eu"]).output


def test_given_versions_when_reading_log_then_they_list_newest_first(tmp_path, monkeypatch):
    monkeypatch.setenv("KYNO_DATABASE_URL", f"sqlite:///{tmp_path / 'c.sqlite3'}")
    runner.invoke(app, ["init-db"])
    apply_yaml(tmp_path, mission="M1", note="first", by="camilo")
    apply_yaml(tmp_path, mission="M2", note="second", by="ci")
    r = runner.invoke(app, ["log"])
    assert r.exit_code == 0
    lines = r.stdout.strip().splitlines()
    assert lines[0].startswith("v2") and "ci" in lines[0] and "second" in lines[0]
    assert lines[1].startswith("v1") and "camilo" in lines[1] and "first" in lines[1]


def test_given_an_empty_store_when_reading_log_then_it_says_so(tmp_path, monkeypatch):
    monkeypatch.setenv("KYNO_DATABASE_URL", f"sqlite:///{tmp_path / 'c.sqlite3'}")
    runner.invoke(app, ["init-db"])
    r = runner.invoke(app, ["log"])
    assert r.exit_code == 0
    assert "no constitution set" in r.stdout
