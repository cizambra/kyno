"""Settings.load(): the workspace is the only config surface; the server
reads no environment variables."""

import pytest

from kyno.config import Settings, store_from_settings
from kyno.errors import ConfigError
from kyno.workspace import create_workspace


def load_from(tmp_path, monkeypatch, body=None):
    root = create_workspace(tmp_path / "ws")
    if body is not None:
        (root / "config" / "server").write_text(body, encoding="utf-8")
    monkeypatch.chdir(root)
    return Settings.load()


def test_given_no_workspace_when_loading_then_the_error_names_kyno_new(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ConfigError, match="no workspace here or above; create one with: kyno new"):
        Settings.load()


def test_given_a_fresh_workspace_when_loading_then_defaults_apply(tmp_path, monkeypatch):
    s = load_from(tmp_path, monkeypatch)
    assert s.database_url.endswith("db/kyno.sqlite3")
    assert s.host == "127.0.0.1" and s.port == 2256
    assert s.allow_insecure is False
    store = store_from_settings(s)
    store.create_all()
    assert store.head("default") is None


def test_given_a_subdirectory_when_loading_then_the_same_workspace_answers(tmp_path, monkeypatch):
    root = create_workspace(tmp_path / "ws")
    below = root / "deep" / "down"
    below.mkdir(parents=True)
    monkeypatch.chdir(below)
    assert Settings.load().database_url.endswith("db/kyno.sqlite3")


def test_given_kyno_token_in_the_environment_when_loading_then_settings_ignore_it(
    tmp_path, monkeypatch
):
    # The variable is retired; serving credentials live in the token table.
    monkeypatch.setenv("KYNO_TOKEN", "hunter2")
    s = load_from(tmp_path, monkeypatch)
    assert "hunter2" not in repr(s)
    assert not hasattr(s, "token")


def test_given_no_page_keys_when_loading_then_the_built_in_look_applies(tmp_path, monkeypatch):
    page = load_from(tmp_path, monkeypatch).page
    assert page.constitution_template is None and page.index_template is None
    assert page.theme.background == "#fbfbf9"
    assert page.theme.uses_custom_colors is False


def test_given_page_keys_when_loading_then_theme_and_templates_follow_them(tmp_path, monkeypatch):
    s = load_from(
        tmp_path,
        monkeypatch,
        "[page]\naccent = #b4531f\nfont_family = Iowan Old Style, serif\n"
        "constitution_template = /srv/constitution.html\nindex_template = pages/index.html\n",
    )
    assert s.page.theme.accent == "#b4531f"
    assert s.page.theme.font_family == "Iowan Old Style, serif"
    assert s.page.constitution_template == "/srv/constitution.html"
    # A relative template anchors at the workspace, like the SQLite path.
    assert s.page.index_template == str(tmp_path / "ws" / "pages" / "index.html")


def test_given_a_style_breaking_page_value_when_loading_then_it_is_refused(tmp_path, monkeypatch):
    with pytest.raises(ConfigError, match="page.accent contains characters"):
        load_from(tmp_path, monkeypatch, "[page]\naccent = red;} body {display:none\n")


def test_given_database_keys_when_loading_then_the_url_reaches_the_store(tmp_path, monkeypatch):
    s = load_from(
        tmp_path, monkeypatch, f"[database]\nadapter = sqlite3\ndatabase = {tmp_path}/own.sqlite3\n"
    )
    assert s.database_url == f"sqlite:///{tmp_path}/own.sqlite3"
