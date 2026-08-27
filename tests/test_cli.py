import json

import pytest
from typer.testing import CliRunner

from kyno.cli import app

runner = CliRunner()


def test_init_set_current_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("KYNO_DATABASE_URL", f"sqlite:///{tmp_path / 'c.sqlite3'}")
    assert runner.invoke(app, ["init-db"]).exit_code == 0
    r = runner.invoke(app, ["set", "--mission", "M1", "--principle", "p1", "--note", "init"])
    assert r.exit_code == 0
    out = runner.invoke(app, ["current"])
    assert out.exit_code == 0
    payload = json.loads(out.stdout)
    assert payload["mission"] == "M1"
    assert payload["principles"] == [{"title": "p1", "description": ""}]


def test_set_requires_note(tmp_path, monkeypatch):
    monkeypatch.setenv("KYNO_DATABASE_URL", f"sqlite:///{tmp_path / 'c.sqlite3'}")
    runner.invoke(app, ["init-db"])
    r = runner.invoke(app, ["set", "--mission", "M1"])
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
    r = runner.invoke(app, ["set", "--mission", "M1", "--note", "init"])
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


def test_set_noop_reports_clean_error(tmp_path, monkeypatch):
    monkeypatch.setenv("KYNO_DATABASE_URL", f"sqlite:///{tmp_path / 'c.sqlite3'}")
    runner.invoke(app, ["init-db"])
    runner.invoke(app, ["set", "--mission", "M1", "--principle", "p1", "--note", "init"])
    r = runner.invoke(app, ["set", "--mission", "M1", "--principle", "p1", "--note", "again"])
    assert r.exit_code == 1
    assert "error:" in r.output.lower()
    assert "Traceback" not in r.output


def test_set_by_records_created_by(tmp_path, monkeypatch):
    monkeypatch.setenv("KYNO_DATABASE_URL", f"sqlite:///{tmp_path / 'c.sqlite3'}")
    runner.invoke(app, ["init-db"])
    r = runner.invoke(
        app, ["set", "--mission", "M1", "--principle", "p1", "--note", "init", "--by", "alice"]
    )
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
    runner.invoke(app, ["set", "--mission", "M1", "--note", "v1"])
    runner.invoke(app, ["set", "--mission", "M2", "--note", "v2"])
    runner.invoke(app, ["set", "--mission", "M3", "--note", "v3"])

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
    r = runner.invoke(
        app,
        ["set", "--constitution", "eu", "--mission", "EU1", "--principle", "p1", "--note", "init"],
    )
    assert r.exit_code == 0
    out = runner.invoke(app, ["current", "--constitution", "eu"])
    assert json.loads(out.stdout)["mission"] == "EU1"
    assert "version 0" in runner.invoke(app, ["current"]).output


def test_named_and_default_constitutions_keep_independent_versions(tmp_path, monkeypatch):
    monkeypatch.setenv("KYNO_DATABASE_URL", f"sqlite:///{tmp_path / 'c.sqlite3'}")
    runner.invoke(app, ["init-db"])
    runner.invoke(app, ["set", "--mission", "M1", "--note", "init"])
    runner.invoke(app, ["set", "--constitution", "eu", "--mission", "EU1", "--note", "init"])
    runner.invoke(app, ["set", "--constitution", "eu", "--mission", "EU2", "--note", "pivot"])

    assert json.loads(runner.invoke(app, ["current"]).stdout)["version"] == 1
    eu = json.loads(runner.invoke(app, ["current", "--constitution", "eu"]).stdout)
    assert eu["version"] == 2 and eu["mission"] == "EU2"

    rows = json.loads(runner.invoke(app, ["export", "--constitution", "eu"]).stdout)
    assert [r["version"] for r in rows] == [1, 2]
    assert len(json.loads(runner.invoke(app, ["export"]).stdout)) == 1


def test_reads_of_an_unknown_constitution_report_the_empty_state(tmp_path, monkeypatch):
    monkeypatch.setenv("KYNO_DATABASE_URL", f"sqlite:///{tmp_path / 'c.sqlite3'}")
    runner.invoke(app, ["init-db"])
    runner.invoke(app, ["set", "--mission", "M1", "--note", "init"])
    r = runner.invoke(app, ["current", "--constitution", "never-written"])
    assert r.exit_code == 0 and "version 0" in r.output
    e = runner.invoke(app, ["export", "--constitution", "never-written"])
    assert e.exit_code == 0 and json.loads(e.stdout) == []


def test_publish_and_unpublish_report_what_changed(tmp_path, monkeypatch):
    monkeypatch.setenv("KYNO_DATABASE_URL", f"sqlite:///{tmp_path / 'c.sqlite3'}")
    runner.invoke(app, ["init-db"])
    runner.invoke(app, ["set", "--mission", "M1", "--note", "init"])

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
    runner.invoke(app, ["set", "--mission", "M1", "--note", "init"])

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
    runner.invoke(app, ["set", "--mission", "M1", "--note", "init"])
    runner.invoke(app, ["set", "--constitution", "eu", "--mission", "EU1", "--note", "init"])

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
    runner.invoke(app, ["set", "--mission", "M1", "--note", "init"])
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
    runner.invoke(app, ["set", "--constitution", "acme/eu", "--mission", "M1", "--note", "init"])
    r = runner.invoke(app, ["publish", "--constitution", "acme/eu"])
    assert r.exit_code == 1
    assert "error:" in r.output.lower()
    assert "Traceback" not in r.output


def test_pull_writes_the_current_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("KYNO_DATABASE_URL", f"sqlite:///{tmp_path / 'c.sqlite3'}")
    runner.invoke(app, ["init-db"])
    runner.invoke(
        app,
        ["set", "--mission", "M1", "--principle", "p1", "--note", "init", "--by", "camilo"],
    )
    target = tmp_path / "constitution.yaml"
    r = runner.invoke(app, ["pull", str(target)])
    assert r.exit_code == 0
    assert "pulled default v1" in r.output
    text = target.read_text(encoding="utf-8")
    assert "constitution: default" in text
    assert "mission: M1" in text
    # Content only: the note and author live in the store, not the file.
    assert "note:" not in text and "by:" not in text


def test_applying_a_pulled_file_changes_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("KYNO_DATABASE_URL", f"sqlite:///{tmp_path / 'c.sqlite3'}")
    runner.invoke(app, ["init-db"])
    runner.invoke(app, ["set", "--mission", "M1", "--principle", "p1", "--note", "init"])
    target = tmp_path / "constitution.yaml"
    runner.invoke(app, ["pull", str(target)])
    r = runner.invoke(app, ["set", "--file", str(target), "--note", "reapply"])
    assert r.exit_code == 1
    assert "no field changed" in r.output


def test_pull_refreshes_a_stale_file(tmp_path, monkeypatch):
    monkeypatch.setenv("KYNO_DATABASE_URL", f"sqlite:///{tmp_path / 'c.sqlite3'}")
    runner.invoke(app, ["init-db"])
    target = tmp_path / "constitution.yaml"
    target.write_text("mission: the old mission\n", encoding="utf-8")
    runner.invoke(app, ["set", "--file", str(target), "--note", "first draft"])
    runner.invoke(app, ["set", "--mission", "the hotfix mission", "--note", "hotfix"])
    r = runner.invoke(app, ["pull", str(target)])
    assert r.exit_code == 0
    text = target.read_text(encoding="utf-8")
    assert "the hotfix mission" in text
    assert "the old mission" not in text


def test_pull_on_an_empty_store_errors(tmp_path, monkeypatch):
    monkeypatch.setenv("KYNO_DATABASE_URL", f"sqlite:///{tmp_path / 'c.sqlite3'}")
    runner.invoke(app, ["init-db"])
    r = runner.invoke(app, ["pull", str(tmp_path / "constitution.yaml")])
    assert r.exit_code == 1
    assert "nothing to pull" in r.output
    assert not (tmp_path / "constitution.yaml").exists()


def test_pulled_file_names_its_constitution(tmp_path, monkeypatch):
    monkeypatch.setenv("KYNO_DATABASE_URL", f"sqlite:///{tmp_path / 'c.sqlite3'}")
    runner.invoke(app, ["init-db"])
    runner.invoke(app, ["set", "--mission", "EU rules", "--note", "init", "--constitution", "eu"])
    target = tmp_path / "eu.yaml"
    runner.invoke(app, ["pull", str(target), "--constitution", "eu"])
    assert "constitution: eu" in target.read_text(encoding="utf-8")
    # The name in the file is enough to route a later apply back to eu.
    r = runner.invoke(app, ["set", "--file", str(target), "--note", "reapply"])
    assert "no field changed" in r.output
