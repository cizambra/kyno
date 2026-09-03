import json

import pytest
from typer.testing import CliRunner

from kyno.cli import app
from tests.workspaces import cli_workspace

runner = CliRunner()


def apply_yaml(
    tmp_path,
    *,
    mission,
    principles=(),
    constitution="default",
    note=None,
    by=None,
    name="applied.yaml",
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
    cli_workspace(monkeypatch, tmp_path, tmp_path / "c.sqlite3")
    assert runner.invoke(app, ["db", "init"]).exit_code == 0
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
    cli_workspace(monkeypatch, tmp_path, tmp_path / "c.sqlite3")
    runner.invoke(app, ["db", "init"])
    r = apply_yaml(tmp_path, mission="M1")
    assert r.exit_code != 0


def test_given_an_uninitialized_db_when_running_current_then_the_error_is_clean(
    tmp_path, monkeypatch
):
    # No db init here: the store raises sqlalchemy.exc.OperationalError,
    # not a kyno CoherenceError. Both must surface as a clean CLI error.
    cli_workspace(monkeypatch, tmp_path, tmp_path / "never_init.sqlite3")
    r = runner.invoke(app, ["current"])
    assert r.exit_code == 1
    assert "error:" in r.output.lower()
    assert "Traceback" not in r.output


def test_given_an_uninitialized_db_when_running_set_then_the_error_is_clean(tmp_path, monkeypatch):
    cli_workspace(monkeypatch, tmp_path, tmp_path / "never_init.sqlite3")
    r = apply_yaml(tmp_path, mission="M1", note="init")
    assert r.exit_code == 1
    assert "error:" in r.output.lower()
    assert "Traceback" not in r.output


def test_given_an_empty_store_when_running_current_then_it_reports_no_constitution_set(
    tmp_path, monkeypatch
):
    cli_workspace(monkeypatch, tmp_path, tmp_path / "c.sqlite3")
    runner.invoke(app, ["db", "init"])
    r = runner.invoke(app, ["current"])
    assert r.exit_code == 0
    assert "version 0" in r.output
    assert "error:" not in r.output.lower()


def test_given_a_by_flag_when_applying_then_the_author_is_recorded(tmp_path, monkeypatch):
    cli_workspace(monkeypatch, tmp_path, tmp_path / "c.sqlite3")
    runner.invoke(app, ["db", "init"])
    r = apply_yaml(tmp_path, mission="M1", principles=["p1"], note="init", by="alice")
    assert r.exit_code == 0
    out = runner.invoke(app, ["current"])
    assert out.exit_code == 0
    payload = json.loads(out.stdout)
    assert payload["created_by"] == "alice"


def _config_lines(root, *lines):
    body = "[database]\nadapter = sqlite3\ndatabase = db/kyno.sqlite3\n" + "\n".join(lines) + "\n"
    (root / "config" / "server").write_text(body, encoding="utf-8")


def test_given_an_invalid_port_when_running_serve_then_the_error_is_clean(monkeypatch, tmp_path):
    root = cli_workspace(monkeypatch, tmp_path)
    _config_lines(root, "[server]", "port = abc")
    r = runner.invoke(app, ["serve", "--transport", "http"])
    assert r.exit_code == 1
    assert "error:" in r.output.lower()
    assert "Traceback" not in r.output


def test_given_the_default_transport_when_serving_then_stdio_runs_the_mcp_server(
    monkeypatch, tmp_path
):
    import anyio

    from kyno.transports import run_stdio

    cli_workspace(monkeypatch, tmp_path)
    heard = {}
    monkeypatch.setattr(anyio, "run", lambda fn, *args: heard.update(fn=fn, args=args))

    r = runner.invoke(app, ["serve"])

    assert r.exit_code == 0, r.output
    assert heard["fn"] is run_stdio


def test_given_a_database_without_the_token_table_when_serving_http_then_it_names_db_upgrade(
    monkeypatch, tmp_path
):
    cli_workspace(monkeypatch, tmp_path)
    r = runner.invoke(app, ["serve", "--transport", "http"])
    assert r.exit_code == 1
    assert "kyno db upgrade" in r.output


def test_given_no_live_tokens_when_serving_http_then_it_names_the_mint_command(
    monkeypatch, tmp_path
):
    cli_workspace(monkeypatch, tmp_path)
    assert runner.invoke(app, ["db", "init"]).exit_code == 0
    r = runner.invoke(app, ["serve", "--transport", "http"])
    assert r.exit_code != 0
    assert "kyno token add NAME --scope write" in r.output


def test_given_kyno_token_in_the_environment_when_serving_http_then_it_changes_nothing(
    monkeypatch, tmp_path
):
    # The variable is retired: serving is decided by the token table alone.
    cli_workspace(monkeypatch, tmp_path)
    assert runner.invoke(app, ["db", "init"]).exit_code == 0
    monkeypatch.setenv("KYNO_TOKEN", "secret")
    r = runner.invoke(app, ["serve", "--transport", "http"])
    assert r.exit_code != 0
    assert "kyno token add NAME --scope write" in r.output


@pytest.mark.parametrize("value", ["true", "TRUE", "1", "yes"])
def test_given_the_insecure_opt_in_when_serving_http_then_the_server_starts_with_a_warning(
    monkeypatch, tmp_path, value
):
    root = cli_workspace(monkeypatch, tmp_path)
    _config_lines(root, "[server]", f"allow_insecure = {value}")
    import uvicorn

    ran = {}
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: ran.setdefault("ran", True))
    r = runner.invoke(app, ["serve", "--transport", "http"])
    assert ran.get("ran") is True
    assert "WARNING" in r.output and "without token checks" in r.output


def test_given_workspace_host_and_port_when_serving_then_uvicorn_receives_them(
    monkeypatch, tmp_path
):
    root = cli_workspace(monkeypatch, tmp_path)
    _config_lines(root, "[server]", "host = 0.0.0.0", "port = 4242", "allow_insecure = true")
    import uvicorn

    heard = {}
    monkeypatch.setattr(uvicorn, "run", lambda served, **kwargs: heard.update(kwargs))
    r = runner.invoke(app, ["serve", "--transport", "http"])
    assert r.exit_code == 0, r.output
    assert heard["host"] == "0.0.0.0" and heard["port"] == 4242


def test_given_a_word_that_is_not_a_boolean_when_serving_http_then_the_error_names_the_key(
    monkeypatch, tmp_path
):
    root = cli_workspace(monkeypatch, tmp_path)
    _config_lines(root, "[server]", "allow_insecure = maybe")
    r = runner.invoke(app, ["serve", "--transport", "http"])
    assert r.exit_code == 1
    assert "server.allow_insecure must be true or false" in r.output
    assert "Traceback" not in r.output


def test_given_written_versions_when_exporting_then_the_history_prints_and_from_bounds_it(
    tmp_path, monkeypatch
):
    cli_workspace(monkeypatch, tmp_path, tmp_path / "c.sqlite3")
    runner.invoke(app, ["db", "init"])
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


def test_given_an_empty_store_when_exporting_then_an_empty_json_array_prints(tmp_path, monkeypatch):
    cli_workspace(monkeypatch, tmp_path, tmp_path / "c.sqlite3")
    runner.invoke(app, ["db", "init"])
    r = runner.invoke(app, ["export"])
    assert r.exit_code == 0
    assert json.loads(r.stdout) == []


def test_given_an_uninitialized_db_when_exporting_then_the_error_is_clean(tmp_path, monkeypatch):
    cli_workspace(monkeypatch, tmp_path, tmp_path / "never_init.sqlite3")
    r = runner.invoke(app, ["export"])
    assert r.exit_code == 1
    assert "error:" in r.output.lower()
    assert "Traceback" not in r.output


def test_given_a_bogus_transport_when_running_serve_then_the_exit_is_argparse_style_2(
    monkeypatch, tmp_path
):
    cli_workspace(monkeypatch, tmp_path, tmp_path / "c.sqlite3")
    r = runner.invoke(app, ["serve", "--transport", "bogus"])
    assert r.exit_code == 2


def test_given_an_apply_to_eu_when_reading_with_the_flag_then_eu_answers_and_default_is_empty(
    tmp_path, monkeypatch
):
    cli_workspace(monkeypatch, tmp_path, tmp_path / "c.sqlite3")
    runner.invoke(app, ["db", "init"])
    r = apply_yaml(tmp_path, mission="EU1", principles=["p1"], constitution="eu", note="init")
    assert r.exit_code == 0
    out = runner.invoke(app, ["current", "--constitution", "eu"])
    assert json.loads(out.stdout)["mission"] == "EU1"
    assert "version 0" in runner.invoke(app, ["current"]).output


def test_given_two_constitutions_when_applying_to_each_then_their_versions_stay_independent(
    tmp_path, monkeypatch
):
    cli_workspace(monkeypatch, tmp_path, tmp_path / "c.sqlite3")
    runner.invoke(app, ["db", "init"])
    apply_yaml(tmp_path, mission="M1", note="init")
    apply_yaml(tmp_path, mission="EU1", constitution="eu", note="init")
    apply_yaml(tmp_path, mission="EU2", constitution="eu", note="pivot")

    assert json.loads(runner.invoke(app, ["current"]).stdout)["version"] == 1
    eu = json.loads(runner.invoke(app, ["current", "--constitution", "eu"]).stdout)
    assert eu["version"] == 2 and eu["mission"] == "EU2"

    rows = json.loads(runner.invoke(app, ["export", "--constitution", "eu"]).stdout)
    assert [r["version"] for r in rows] == [1, 2]
    assert len(json.loads(runner.invoke(app, ["export"]).stdout)) == 1


def test_given_an_unknown_constitution_when_reading_then_the_empty_state_is_reported(
    tmp_path, monkeypatch
):
    cli_workspace(monkeypatch, tmp_path, tmp_path / "c.sqlite3")
    runner.invoke(app, ["db", "init"])
    apply_yaml(tmp_path, mission="M1", note="init")
    r = runner.invoke(app, ["current", "--constitution", "never-written"])
    assert r.exit_code == 0 and "version 0" in r.output
    e = runner.invoke(app, ["export", "--constitution", "never-written"])
    assert e.exit_code == 0 and json.loads(e.stdout) == []


def test_given_a_constitution_when_publishing_and_unpublishing_then_each_reports_what_changed(
    tmp_path, monkeypatch
):
    cli_workspace(monkeypatch, tmp_path, tmp_path / "c.sqlite3")
    runner.invoke(app, ["db", "init"])
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


def test_given_the_history_flag_when_publishing_then_the_output_says_whether_history_is_public(
    tmp_path, monkeypatch
):
    cli_workspace(monkeypatch, tmp_path, tmp_path / "c.sqlite3")
    runner.invoke(app, ["db", "init"])
    apply_yaml(tmp_path, mission="M1", note="init")

    quiet = runner.invoke(app, ["publish"])
    assert "history" in quiet.output.lower()
    assert "hidden" in quiet.output.lower()

    loud = runner.invoke(app, ["publish", "--with-history"])
    assert loud.exit_code == 0
    assert "history" in loud.output.lower()
    assert "public" in loud.output.lower()


def test_given_no_name_when_publishing_then_the_default_is_used_and_the_flag_overrides(
    tmp_path, monkeypatch
):
    cli_workspace(monkeypatch, tmp_path, tmp_path / "c.sqlite3")
    runner.invoke(app, ["db", "init"])
    apply_yaml(tmp_path, mission="M1", note="init")
    apply_yaml(tmp_path, mission="EU1", constitution="eu", note="init")

    r = runner.invoke(app, ["publish", "--constitution", "eu"])
    assert r.exit_code == 0
    assert "/constitutions/eu" in r.output


def test_given_a_constitution_with_no_direction_when_publishing_then_the_error_is_clean(
    tmp_path, monkeypatch
):
    cli_workspace(monkeypatch, tmp_path, tmp_path / "c.sqlite3")
    runner.invoke(app, ["db", "init"])
    r = runner.invoke(app, ["publish", "--constitution", "never-written"])
    assert r.exit_code == 1
    assert "error:" in r.output.lower()
    assert "Traceback" not in r.output


def test_given_an_unknown_constitution_when_unpublishing_then_the_error_is_clean(
    tmp_path, monkeypatch
):
    # A typo here must not print success while the real page stays public.
    cli_workspace(monkeypatch, tmp_path, tmp_path / "c.sqlite3")
    runner.invoke(app, ["db", "init"])
    apply_yaml(tmp_path, mission="M1", note="init")
    r = runner.invoke(app, ["unpublish", "--constitution", "defualt"])
    assert r.exit_code == 1
    assert "error:" in r.output.lower()
    assert "Traceback" not in r.output


def test_given_an_uninitialized_db_when_publishing_then_the_error_is_clean(tmp_path, monkeypatch):
    cli_workspace(monkeypatch, tmp_path, tmp_path / "never_init.sqlite3")
    r = runner.invoke(app, ["publish"])
    assert r.exit_code == 1
    assert "error:" in r.output.lower()
    assert "Traceback" not in r.output


def test_given_a_name_with_a_slash_when_publishing_then_it_is_refused_without_a_traceback(
    tmp_path, monkeypatch
):
    cli_workspace(monkeypatch, tmp_path, tmp_path / "c.sqlite3")
    runner.invoke(app, ["db", "init"])
    apply_yaml(tmp_path, mission="M1", constitution="acme/eu", note="init")
    r = runner.invoke(app, ["publish", "--constitution", "acme/eu"])
    assert r.exit_code == 1
    assert "error:" in r.output.lower()
    assert "Traceback" not in r.output


def test_given_a_head_when_reading_current_yaml_then_it_prints_in_file_format(
    tmp_path, monkeypatch
):
    cli_workspace(monkeypatch, tmp_path, tmp_path / "c.sqlite3")
    runner.invoke(app, ["db", "init"])
    apply_yaml(tmp_path, mission="M1", principles=["p1"], note="init", by="camilo")
    r = runner.invoke(app, ["current", "--yaml"])
    assert r.exit_code == 0
    assert "constitution: default" in r.stdout
    assert "mission: M1" in r.stdout
    # Content only: the note and author live in the store, not the output.
    assert "note:" not in r.stdout and "by:" not in r.stdout


def test_given_the_yaml_read_out_when_reapplied_then_nothing_changes(tmp_path, monkeypatch):
    cli_workspace(monkeypatch, tmp_path, tmp_path / "c.sqlite3")
    runner.invoke(app, ["db", "init"])
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
    cli_workspace(monkeypatch, tmp_path, tmp_path / "c.sqlite3")
    runner.invoke(app, ["db", "init"])
    apply_yaml(tmp_path, mission="the old mission", note="first")
    apply_yaml(tmp_path, mission="the hotfix mission", note="hotfix")
    out = runner.invoke(app, ["current", "--yaml"]).stdout
    assert "the hotfix mission" in out
    assert "the old mission" not in out


def test_given_an_empty_store_when_reading_current_yaml_then_it_errors(tmp_path, monkeypatch):
    cli_workspace(monkeypatch, tmp_path, tmp_path / "c.sqlite3")
    runner.invoke(app, ["db", "init"])
    r = runner.invoke(app, ["current", "--yaml"])
    assert r.exit_code == 1
    assert "nothing to read" in r.output


def test_given_a_named_constitution_when_reading_current_yaml_then_the_name_routes_a_reapply(
    tmp_path, monkeypatch
):
    cli_workspace(monkeypatch, tmp_path, tmp_path / "c.sqlite3")
    runner.invoke(app, ["db", "init"])
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

    cli_workspace(monkeypatch, tmp_path, tmp_path / "c.sqlite3")
    runner.invoke(app, ["db", "init"])
    r = apply_yaml(tmp_path, mission="M1", note="init")
    assert r.exit_code == 0
    assert json.loads(r.stdout)["created_by"] == getpass.getuser()


def test_given_typos_and_custom_keys_when_checking_then_the_report_lists_them_without_blocking(
    tmp_path, monkeypatch
):
    cli_workspace(monkeypatch, tmp_path, tmp_path / "c.sqlite3")
    target = tmp_path / "constitution.yaml"
    target.write_text(
        "constitution: default\nmission: M\nprincipals:\n  - p1\nnote: n\n", encoding="utf-8"
    )
    r = runner.invoke(app, ["check", str(target)])
    assert r.exit_code == 0
    assert "kyno fields set: constitution, mission" in r.output
    assert "principles" in r.output
    assert "note, principals" in r.output


def test_given_an_unparseable_file_when_checking_then_it_errors(tmp_path, monkeypatch):
    cli_workspace(monkeypatch, tmp_path, tmp_path / "c.sqlite3")
    target = tmp_path / "constitution.yaml"
    target.write_text("mission: [unclosed\n", encoding="utf-8")
    r = runner.invoke(app, ["check", str(target)])
    assert r.exit_code == 1
    assert "error:" in r.output


def test_given_custom_fields_when_applying_then_they_are_ignored(tmp_path, monkeypatch):
    cli_workspace(monkeypatch, tmp_path, tmp_path / "c.sqlite3")
    runner.invoke(app, ["db", "init"])
    target = tmp_path / "constitution.yaml"
    target.write_text(
        "constitution: default\nmission: M1\nnote: the file note\nteam: lending\n", encoding="utf-8"
    )
    r = runner.invoke(app, ["set", str(target), "--note", "the real note"])
    assert r.exit_code == 0
    payload = json.loads(r.stdout)
    assert payload["change_note"] == "the real note"


def test_given_an_edit_when_applied_then_the_delta_is_printed(tmp_path, monkeypatch):
    cli_workspace(monkeypatch, tmp_path, tmp_path / "c.sqlite3")
    runner.invoke(app, ["db", "init"])
    apply_yaml(tmp_path, mission="M1", note="init")
    r = apply_yaml(tmp_path, mission="M2", note="pivot")
    assert r.exit_code == 0
    assert 'The mission was "M1" and is now "M2".' in r.output
    # stdout stays the version JSON so it can be piped; the delta goes to stderr.
    assert json.loads(r.stdout)["version"] == 2


def test_given_an_empty_store_when_applying_then_the_first_version_is_announced(
    tmp_path, monkeypatch
):
    cli_workspace(monkeypatch, tmp_path, tmp_path / "c.sqlite3")
    runner.invoke(app, ["db", "init"])
    r = apply_yaml(tmp_path, mission="M1", note="init")
    assert "Creates 'default' at version 1." in r.output


def test_given_dry_run_when_applying_then_the_delta_prints_and_nothing_is_persisted(
    tmp_path, monkeypatch
):
    cli_workspace(monkeypatch, tmp_path, tmp_path / "c.sqlite3")
    runner.invoke(app, ["db", "init"])
    apply_yaml(tmp_path, mission="M1", note="init")
    target = tmp_path / "next.yaml"
    target.write_text("constitution: default\nmission: M2\n", encoding="utf-8")
    r = runner.invoke(app, ["set", str(target), "--dry-run"])
    assert r.exit_code == 0
    assert 'The mission was "M1" and is now "M2".' in r.output
    head = json.loads(runner.invoke(app, ["current"]).stdout)
    assert head["version"] == 1 and head["mission"] == "M1"


def test_given_identical_content_when_dry_running_then_it_says_no_field_changed(
    tmp_path, monkeypatch
):
    cli_workspace(monkeypatch, tmp_path, tmp_path / "c.sqlite3")
    runner.invoke(app, ["db", "init"])
    apply_yaml(tmp_path, mission="M1", note="init", name="same.yaml")
    r = runner.invoke(app, ["set", str(tmp_path / "same.yaml"), "--dry-run"])
    assert r.exit_code == 0
    assert "no field changed" in r.output


def test_given_dry_run_when_no_note_is_passed_then_it_still_runs(tmp_path, monkeypatch):
    cli_workspace(monkeypatch, tmp_path, tmp_path / "c.sqlite3")
    runner.invoke(app, ["db", "init"])
    target = tmp_path / "next.yaml"
    target.write_text("constitution: default\nmission: M1\n", encoding="utf-8")
    r = runner.invoke(app, ["set", str(target), "--dry-run"])
    assert r.exit_code == 0


def test_given_an_apply_when_reading_stdout_then_the_json_is_indented_for_people(
    tmp_path, monkeypatch
):
    """The JSON is read by people at a terminal as often as by scripts, and
    indentation costs a script nothing. `current` and `export` match."""
    cli_workspace(monkeypatch, tmp_path, tmp_path / "c.sqlite3")
    runner.invoke(app, ["db", "init"])
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
    cli_workspace(monkeypatch, tmp_path, tmp_path / "c.sqlite3")
    runner.invoke(app, ["db", "init"])
    apply_yaml(tmp_path, mission="M1", note="init", name="same.yaml")
    r = runner.invoke(app, ["set", str(tmp_path / "same.yaml"), "--note", "again"])
    assert r.exit_code == 0
    assert "no field changed" in r.output
    assert json.loads(r.stdout)["version"] == 1
    assert json.loads(runner.invoke(app, ["current"]).stdout)["version"] == 1


def test_given_a_whitespace_note_when_applying_then_it_is_refused_as_missing(tmp_path, monkeypatch):
    cli_workspace(monkeypatch, tmp_path, tmp_path / "c.sqlite3")
    runner.invoke(app, ["db", "init"])
    r = apply_yaml(tmp_path, mission="M1", note="   ")
    assert r.exit_code != 0
    assert "note" in r.output.lower()


def test_given_a_file_without_a_constitution_key_when_applying_then_it_is_refused_with_the_fix(
    tmp_path, monkeypatch
):
    """The name is part of the content: a file that does not say which
    constitution it is cannot be applied anywhere, not even to default."""
    cli_workspace(monkeypatch, tmp_path, tmp_path / "c.sqlite3")
    runner.invoke(app, ["db", "init"])
    r = apply_yaml(tmp_path, mission="M1", note="init", constitution=None)
    assert r.exit_code == 1
    assert "constitution: <name>" in r.output
    assert "no constitution set" in runner.invoke(app, ["current"]).output


def test_given_versions_when_reading_log_then_they_list_newest_first(tmp_path, monkeypatch):
    cli_workspace(monkeypatch, tmp_path, tmp_path / "c.sqlite3")
    runner.invoke(app, ["db", "init"])
    apply_yaml(tmp_path, mission="M1", note="first", by="camilo")
    apply_yaml(tmp_path, mission="M2", note="second", by="ci")
    r = runner.invoke(app, ["log"])
    assert r.exit_code == 0
    lines = r.stdout.strip().splitlines()
    assert lines[0].startswith("v2") and "ci" in lines[0] and "second" in lines[0]
    assert lines[1].startswith("v1") and "camilo" in lines[1] and "first" in lines[1]


def test_given_an_empty_store_when_reading_log_then_it_says_so(tmp_path, monkeypatch):
    cli_workspace(monkeypatch, tmp_path, tmp_path / "c.sqlite3")
    runner.invoke(app, ["db", "init"])
    r = runner.invoke(app, ["log"])
    assert r.exit_code == 0
    assert "no constitution set" in r.stdout


def test_given_a_matching_file_when_checking_then_the_store_agrees(tmp_path, monkeypatch):
    cli_workspace(monkeypatch, tmp_path, tmp_path / "c.sqlite3")
    runner.invoke(app, ["db", "init"])
    apply_yaml(tmp_path, mission="M1", note="init", name="c.yaml")
    r = runner.invoke(app, ["check", str(tmp_path / "c.yaml")])
    assert r.exit_code == 0
    assert "store: agrees with 'default' (version 1)" in r.stdout


def test_given_a_stale_file_when_checking_then_it_fails_and_shows_the_delta(tmp_path, monkeypatch):
    cli_workspace(monkeypatch, tmp_path, tmp_path / "c.sqlite3")
    runner.invoke(app, ["db", "init"])
    apply_yaml(tmp_path, mission="M2", note="hotfix")
    stale = tmp_path / "stale.yaml"
    stale.write_text("constitution: default\nmission: M1\n", encoding="utf-8")
    r = runner.invoke(app, ["check", str(stale)])
    assert r.exit_code == 1
    assert "store: differs from 'default' (version 1):" in r.stdout
    assert 'The mission was "M2" and is now "M1".' in r.stdout


def test_given_an_empty_store_when_checking_then_it_fails(tmp_path, monkeypatch):
    cli_workspace(monkeypatch, tmp_path, tmp_path / "c.sqlite3")
    runner.invoke(app, ["db", "init"])
    target = tmp_path / "c.yaml"
    target.write_text("constitution: default\nmission: M1\n", encoding="utf-8")
    r = runner.invoke(app, ["check", str(target)])
    assert r.exit_code == 1
    assert "has no versions" in r.stdout


def test_given_an_unreachable_store_when_checking_then_the_report_still_prints(
    tmp_path, monkeypatch
):
    # No db init: the field report stands, the comparison says why it didn't run.
    cli_workspace(monkeypatch, tmp_path, tmp_path / "never.sqlite3")
    target = tmp_path / "c.yaml"
    target.write_text("constitution: default\nmission: M1\n", encoding="utf-8")
    r = runner.invoke(app, ["check", str(target)])
    assert r.exit_code == 0
    assert "kyno fields set: constitution, mission" in r.stdout
    assert "store: not compared" in r.stdout
    assert "[SQL:" not in r.stdout and r.stdout.count("store:") == 1


def test_given_a_file_without_a_constitution_key_when_checking_then_the_store_is_not_compared(
    tmp_path, monkeypatch
):
    cli_workspace(monkeypatch, tmp_path, tmp_path / "c.sqlite3")
    runner.invoke(app, ["db", "init"])
    target = tmp_path / "unnamed.yaml"
    target.write_text("mission: M1\n", encoding="utf-8")
    r = runner.invoke(app, ["check", str(target)])
    assert r.exit_code == 1
    assert "kyno fields not set: constitution" in r.output
    assert "store: not compared" in r.output and "constitution: <name>" in r.output


def test_given_a_check_when_comparing_with_the_store_then_the_head_is_read_once(
    tmp_path, monkeypatch
):
    """One read feeds both the version named and the delta shown, so a
    writer landing mid-check cannot make the two describe different heads."""
    from kyno.store.sql import SqlConstitutionStore

    cli_workspace(monkeypatch, tmp_path, tmp_path / "c.sqlite3")
    runner.invoke(app, ["db", "init"])
    apply_yaml(tmp_path, mission="M1", note="init", name="c.yaml")
    reads = []
    real_head = SqlConstitutionStore.head
    monkeypatch.setattr(
        SqlConstitutionStore, "head", lambda self, name: reads.append(name) or real_head(self, name)
    )
    r = runner.invoke(app, ["check", str(tmp_path / "c.yaml")])
    assert r.exit_code == 0 and "agrees" in r.output
    assert reads == ["default"]


@pytest.mark.parametrize("command", [["db", "init"], ["db", "upgrade"]])
def test_given_a_malformed_database_url_when_preparing_the_db_then_the_error_is_clean(
    monkeypatch, tmp_path, command
):
    root = cli_workspace(monkeypatch, tmp_path)
    (root / "config" / "server").write_text(
        "[database]\nurl = not-a-database-url\n", encoding="utf-8"
    )
    r = runner.invoke(app, command)
    assert r.exit_code == 1
    assert "error:" in r.output and "Traceback" not in r.output


def test_given_no_system_username_when_applying_then_created_by_is_empty(tmp_path, monkeypatch):
    """getpass can fail on stripped-down systems; the apply still works and
    the author is simply not recorded."""
    import getpass

    cli_workspace(monkeypatch, tmp_path, tmp_path / "c.sqlite3")
    runner.invoke(app, ["db", "init"])

    def refuse():
        raise OSError("no user database")

    monkeypatch.setattr(getpass, "getuser", refuse)
    r = apply_yaml(tmp_path, mission="M1", note="init")
    assert r.exit_code == 0, r.output
    assert json.loads(r.stdout)["created_by"] is None


def test_given_an_unwritable_target_when_exporting_pages_then_the_error_is_clean(
    tmp_path, monkeypatch
):
    import os

    if os.geteuid() == 0:
        pytest.skip("root ignores directory permissions")
    target = tmp_path / "locked"
    target.mkdir()
    target.chmod(0o500)
    r = runner.invoke(app, ["page", "export", str(target / "inside")])
    assert r.exit_code == 1
    assert "error:" in r.output and "Traceback" not in r.output


def test_given_the_stdio_transport_when_serving_then_run_stdio_is_dispatched(tmp_path, monkeypatch):
    import anyio

    cli_workspace(monkeypatch, tmp_path, tmp_path / "c.sqlite3")
    runner.invoke(app, ["db", "init"])
    dispatched = {}
    monkeypatch.setattr(anyio, "run", lambda fn, cp: dispatched.update(fn=fn.__name__, cp=cp))
    r = runner.invoke(app, ["serve", "--transport", "stdio"])
    assert r.exit_code == 0, r.output
    assert dispatched["fn"] == "run_stdio"
    from kyno.service import ControlPlane

    assert isinstance(dispatched["cp"], ControlPlane)


def test_given_a_local_apply_when_reading_the_version_then_no_authorization_is_recorded(
    tmp_path, monkeypatch
):
    """Local applies have no questions, so there is nothing to record."""
    cli_workspace(monkeypatch, tmp_path, tmp_path / "c.sqlite3")
    runner.invoke(app, ["db", "init"])
    r = apply_yaml(tmp_path, mission="M1", note="init")
    assert r.exit_code == 0, r.output
    assert json.loads(r.stdout)["authorized_by"] is None


def test_given_a_local_version_when_reading_log_then_the_authorization_column_is_a_dash(
    tmp_path, monkeypatch
):
    cli_workspace(monkeypatch, tmp_path, tmp_path / "c.sqlite3")
    runner.invoke(app, ["db", "init"])
    apply_yaml(tmp_path, mission="M1", note="first", by="camilo")
    line = runner.invoke(app, ["log"]).stdout.strip().splitlines()[0]
    assert line.split()[:4] == ["v1", line.split()[1], "camilo", "-"]
