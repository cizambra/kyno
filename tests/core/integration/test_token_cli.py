"""kyno token add / list / revoke, against the design's console samples."""

import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from typer.testing import CliRunner

from kyno.cli import app
from kyno.config import Settings, store_from_settings
from kyno.tokens import hash_value
from tests.workspaces import cli_workspace

runner = CliRunner()

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _plain(text):
    # Typer colors its error panels; asserting on styled text would couple
    # the test to the palette.
    return _ANSI.sub("", text)


def _workspace(monkeypatch, tmp_path):
    cli_workspace(monkeypatch, tmp_path)
    assert runner.invoke(app, ["db", "init"]).exit_code == 0


def _store():
    return store_from_settings(Settings.load())


def test_given_a_workspace_when_minting_then_the_value_prints_and_only_its_hash_is_stored(
    monkeypatch, tmp_path
):
    _workspace(monkeypatch, tmp_path)

    result = runner.invoke(app, ["token", "add", "ci", "--scope", "write"])

    assert result.exit_code == 0, result.output
    value = result.output.strip()
    assert value.startswith("kyno_")
    with _store().engine.connect() as conn:
        stored = conn.execute(text("SELECT token_hash FROM kyno_tokens")).scalar()
    assert stored == hash_value(value)
    assert stored != value


def test_given_an_unknown_scope_when_minting_then_it_refuses_naming_the_choices(
    monkeypatch, tmp_path
):
    _workspace(monkeypatch, tmp_path)

    result = runner.invoke(app, ["token", "add", "ci", "--scope", "admin"])

    assert result.exit_code == 1
    assert "unknown scope 'admin'" in result.output
    assert "read or write" in result.output
    assert _store().tokens() == []


def test_given_a_ttl_when_minting_then_the_token_expires_on_its_own(monkeypatch, tmp_path):
    _workspace(monkeypatch, tmp_path)
    before = datetime.now(UTC)

    result = runner.invoke(app, ["token", "add", "hotfix", "--scope", "write", "--ttl", "2h"])

    assert result.exit_code == 0, result.output
    t = _store().tokens()[0]
    assert t.expires_at is not None
    assert timedelta(hours=1, minutes=59) < (t.expires_at - before) <= timedelta(hours=2, minutes=1)

    # Expiry takes effect on its own: once the moment passes, the token
    # drops out of the live list with no revoke in between.
    with _store().engine.begin() as conn:
        conn.execute(
            text("UPDATE kyno_tokens SET expires_at = :t"),
            {"t": datetime.now(UTC) - timedelta(seconds=1)},
        )
    assert "hotfix" not in runner.invoke(app, ["token", "list"]).output
    everything = runner.invoke(app, ["token", "list", "--all"])
    assert any("hotfix" in ln and ln.endswith("expired") for ln in everything.output.splitlines())


def test_given_a_ttl_that_is_not_a_number_and_a_unit_when_minting_then_nothing_is_minted(
    monkeypatch, tmp_path
):
    _workspace(monkeypatch, tmp_path)

    result = runner.invoke(app, ["token", "add", "x", "--scope", "read", "--ttl", "2w"])

    assert result.exit_code == 1
    assert "'2w'" in result.output
    assert _store().tokens() == []


def test_given_no_workspace_when_minting_then_it_refuses_with_the_workspace_hint(
    monkeypatch, tmp_path
):
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["token", "add", "ci", "--scope", "write"])

    assert result.exit_code == 1
    assert "no workspace" in result.output


def test_given_live_and_dead_tokens_when_listing_then_only_all_shows_the_dead_with_their_state(
    monkeypatch, tmp_path
):
    _workspace(monkeypatch, tmp_path)
    assert runner.invoke(app, ["token", "add", "ci", "--scope", "write"]).exit_code == 0
    assert runner.invoke(app, ["token", "add", "old", "--scope", "read"]).exit_code == 0
    store = _store()
    old = next(t for t in store.tokens() if t.name == "old")
    assert store.revoke_token(old.id)
    # An already-expired loaner, written directly: the CLI has no way to
    # mint one that is born dead.
    store.add_token(
        "loaner", "read", token_hash="e" * 64, expires_at=datetime.now(UTC) - timedelta(hours=1)
    )

    live = runner.invoke(app, ["token", "list"])
    assert live.exit_code == 0
    assert "ci" in live.output
    assert "old" not in live.output and "loaner" not in live.output

    everything = runner.invoke(app, ["token", "list", "--all"])
    lines = everything.output.splitlines()
    assert any("old" in ln and ln.endswith("revoked") for ln in lines)
    assert any("loaner" in ln and ln.endswith("expired") for ln in lines)
    assert any("ci" in ln and not ln.endswith(("revoked", "expired")) for ln in lines)


def test_given_a_never_used_token_when_listing_then_last_used_reads_never(monkeypatch, tmp_path):
    _workspace(monkeypatch, tmp_path)
    assert runner.invoke(app, ["token", "add", "ci", "--scope", "write"]).exit_code == 0

    result = runner.invoke(app, ["token", "list"])

    assert result.exit_code == 0
    assert "created" in result.output
    assert "last used never" in result.output


def test_given_no_tokens_when_listing_then_it_says_how_to_mint_one(monkeypatch, tmp_path):
    _workspace(monkeypatch, tmp_path)

    result = runner.invoke(app, ["token", "list"])

    assert result.exit_code == 0
    assert "kyno token add" in result.output
    assert runner.invoke(app, ["token", "list", "--all"]).output.strip() == "no tokens"


def test_given_a_unique_live_name_when_revoking_by_name_then_the_row_is_revoked_and_kept(
    monkeypatch, tmp_path
):
    _workspace(monkeypatch, tmp_path)
    assert runner.invoke(app, ["token", "add", "ci", "--scope", "write"]).exit_code == 0

    result = runner.invoke(app, ["token", "revoke", "ci"])

    assert result.exit_code == 0
    rows = _store().tokens()
    assert len(rows) == 1
    assert rows[0].revoked_at is not None


def test_given_two_live_tokens_sharing_a_name_when_revoking_by_name_then_it_asks_for_the_id(
    monkeypatch, tmp_path
):
    # The rotation overlap: both live, same name, resolved by id.
    _workspace(monkeypatch, tmp_path)
    assert runner.invoke(app, ["token", "add", "ci", "--scope", "write"]).exit_code == 0
    assert runner.invoke(app, ["token", "add", "ci", "--scope", "write"]).exit_code == 0

    result = runner.invoke(app, ["token", "revoke", "ci"])

    assert result.exit_code == 1
    ids = sorted(t.id for t in _store().tokens())
    assert f"ids {ids[0]}, {ids[1]}" in result.output
    assert "--id" in result.output

    done = runner.invoke(app, ["token", "revoke", "--id", str(ids[0])])
    assert done.exit_code == 0
    now = datetime.now(UTC)
    assert [t.id for t in _store().tokens() if t.live_at(now)] == [ids[1]]


def test_given_a_name_and_an_id_together_when_revoking_then_it_refuses(monkeypatch, tmp_path):
    _workspace(monkeypatch, tmp_path)

    result = runner.invoke(app, ["token", "revoke", "ci", "--id", "1"])

    assert result.exit_code == 1
    assert "one way" in result.output


def test_given_neither_name_nor_id_when_revoking_then_it_refuses(monkeypatch, tmp_path):
    _workspace(monkeypatch, tmp_path)

    result = runner.invoke(app, ["token", "revoke"])

    assert result.exit_code == 1
    assert "one way" in result.output


def test_given_an_unknown_name_when_revoking_then_it_refuses_naming_it(monkeypatch, tmp_path):
    _workspace(monkeypatch, tmp_path)

    result = runner.invoke(app, ["token", "revoke", "ghost"])

    assert result.exit_code == 1
    assert "no live token named 'ghost'" in result.output


def test_given_an_already_revoked_id_when_revoking_then_it_says_so(monkeypatch, tmp_path):
    _workspace(monkeypatch, tmp_path)
    assert runner.invoke(app, ["token", "add", "ci", "--scope", "write"]).exit_code == 0
    assert runner.invoke(app, ["token", "revoke", "ci"]).exit_code == 0
    token_id = _store().tokens()[0].id

    result = runner.invoke(app, ["token", "revoke", "--id", str(token_id)])

    assert result.exit_code == 1
    assert "already revoked" in result.output


def test_given_an_unknown_id_when_revoking_then_it_says_so(monkeypatch, tmp_path):
    _workspace(monkeypatch, tmp_path)

    result = runner.invoke(app, ["token", "revoke", "--id", "99"])

    assert result.exit_code == 1
    assert "no token with id 99" in result.output


def test_given_no_scope_when_minting_then_it_refuses_before_touching_anything(
    monkeypatch, tmp_path
):
    _workspace(monkeypatch, tmp_path)

    result = runner.invoke(app, ["token", "add", "ci"])

    assert result.exit_code == 2
    assert "Missing option '--scope'" in _plain(result.output)
    assert _store().tokens() == []


def test_given_a_used_token_when_listing_then_last_used_shows_the_age(monkeypatch, tmp_path):
    _workspace(monkeypatch, tmp_path)
    assert runner.invoke(app, ["token", "add", "ci", "--scope", "write"]).exit_code == 0
    # The server-side touch arrives with the serving switch; until then the
    # column is written directly to test the read path.
    two_minutes_ago = datetime.now(UTC) - timedelta(minutes=2)
    with _store().engine.begin() as conn:
        conn.execute(text("UPDATE kyno_tokens SET last_used_at = :t"), {"t": two_minutes_ago})

    result = runner.invoke(app, ["token", "list"])

    assert result.exit_code == 0
    assert "last used 2m ago" in result.output


def test_given_an_expired_token_when_revoking_then_name_and_id_paths_both_refuse(
    monkeypatch, tmp_path
):
    # An expired token already stopped working, so revoking it would
    # record the wrong cause. Refusing keeps the row accurate.
    _workspace(monkeypatch, tmp_path)
    store = _store()
    t = store.add_token(
        "loaner", "read", token_hash="f" * 64, expires_at=datetime.now(UTC) - timedelta(hours=1)
    )

    by_name = runner.invoke(app, ["token", "revoke", "loaner"])
    assert by_name.exit_code == 1
    assert "no live token named 'loaner'" in by_name.output

    by_id = runner.invoke(app, ["token", "revoke", "--id", str(t.id)])
    assert by_id.exit_code == 1
    assert "already expired" in by_id.output
    assert store.token(t.id).revoked_at is None
