import pytest

from kyno.config import Settings, store_from_settings
from kyno.errors import ConfigError


def test_given_a_bare_environment_when_loading_settings_then_defaults_apply(monkeypatch):
    for k in (
        "KYNO_DATABASE_URL",
        "KYNO_TOKEN",
        "KYNO_TABLE_PREFIX",
        "KYNO_HOST",
        "KYNO_PORT",
    ):
        monkeypatch.delenv(k, raising=False)
    s = Settings.from_env()
    assert s.database_url == "sqlite:///kyno.sqlite3"
    assert s.token is None and s.table_prefix == "kyno_"
    assert s.host == "127.0.0.1" and s.port == 8080


def test_given_env_overrides_when_loading_settings_then_they_take_effect(monkeypatch):
    monkeypatch.setenv("KYNO_DATABASE_URL", "sqlite://")
    monkeypatch.setenv("KYNO_TOKEN", "secret")
    monkeypatch.setenv("KYNO_TABLE_PREFIX", "cp_")
    s = Settings.from_env()
    assert s.token == "secret" and s.table_prefix == "cp_"
    store = store_from_settings(s)
    store.create_all()
    assert store.head("default") is None


def test_given_a_non_integer_port_when_loading_settings_then_it_is_refused(monkeypatch):
    monkeypatch.setenv("KYNO_PORT", "abc")
    with pytest.raises(ConfigError, match="KYNO_PORT must be an integer, got 'abc'"):
        Settings.from_env()


@pytest.mark.parametrize("value", ["", "   ", "\t\n"])
def test_given_a_blank_token_when_loading_settings_then_it_is_refused_not_quietly_tokenless(
    monkeypatch, value
):
    # `KYNO_TOKEN=""` reads as "auth is on" to the person who set it; the
    # only honest answers are a working token or a loud refusal.
    monkeypatch.setenv("KYNO_TOKEN", value)
    with pytest.raises(ConfigError, match="KYNO_TOKEN"):
        Settings.from_env()


def test_given_no_token_when_loading_settings_then_it_reads_as_none(monkeypatch):
    monkeypatch.delenv("KYNO_TOKEN", raising=False)
    assert Settings.from_env().token is None


def test_given_a_token_when_printing_settings_then_the_token_never_appears(monkeypatch):
    monkeypatch.setenv("KYNO_TOKEN", "hunter2")
    assert "hunter2" not in repr(Settings.from_env())


@pytest.mark.parametrize("value", ["kyno_;drop table x;--", "pre fix_", "pré_", "a-b_", ""])
def test_given_a_non_identifier_table_prefix_when_loading_settings_then_it_is_refused(
    monkeypatch, value
):
    # The prefix is interpolated into DDL identifiers; it is never allowed
    # to be anything but a plain identifier fragment.
    monkeypatch.setenv("KYNO_TABLE_PREFIX", value)
    with pytest.raises(ConfigError, match="KYNO_TABLE_PREFIX"):
        Settings.from_env()


def test_given_a_plain_identifier_table_prefix_when_loading_settings_then_it_is_accepted(
    monkeypatch,
):
    monkeypatch.setenv("KYNO_TABLE_PREFIX", "Team_42_")
    assert Settings.from_env().table_prefix == "Team_42_"


def test_given_host_and_port_env_vars_when_loading_settings_then_they_take_effect(monkeypatch):
    monkeypatch.setenv("KYNO_HOST", "0.0.0.0")
    monkeypatch.setenv("KYNO_PORT", "9999")
    s = Settings.from_env()
    assert s.host == "0.0.0.0"
    assert s.port == 9999


_PAGE_ENV = (
    "KYNO_PAGE_ACCENT",
    "KYNO_PAGE_BACKGROUND",
    "KYNO_PAGE_TEXT",
    "KYNO_PAGE_MUTED",
    "KYNO_PAGE_RULE",
    "KYNO_PAGE_FONT",
    "KYNO_CONSTITUTION_TEMPLATE",
    "KYNO_INDEX_TEMPLATE",
)


def _clear_page_env(monkeypatch):
    for k in _PAGE_ENV:
        monkeypatch.delenv(k, raising=False)


def test_given_no_page_env_when_loading_settings_then_the_built_in_look_applies(monkeypatch):
    _clear_page_env(monkeypatch)
    page = Settings.from_env().page
    assert page.constitution_template is None and page.index_template is None
    assert page.theme.background == "#fbfbf9"
    assert page.theme.uses_custom_colors is False


def test_given_page_env_vars_when_loading_settings_then_theme_and_templates_follow_them(
    monkeypatch,
):
    _clear_page_env(monkeypatch)
    monkeypatch.setenv("KYNO_PAGE_ACCENT", "#b4531f")
    monkeypatch.setenv("KYNO_PAGE_FONT", "Iowan Old Style, serif")
    monkeypatch.setenv("KYNO_CONSTITUTION_TEMPLATE", "/srv/constitution.html")
    monkeypatch.setenv("KYNO_INDEX_TEMPLATE", "/srv/index.html")

    page = Settings.from_env().page
    assert page.theme.accent == "#b4531f"
    assert page.theme.font_family == "Iowan Old Style, serif"
    assert page.theme.uses_custom_colors is True
    assert page.constitution_template == "/srv/constitution.html"
    assert page.index_template == "/srv/index.html"


def test_given_an_empty_page_env_var_when_loading_settings_then_it_reads_as_unset(monkeypatch):
    _clear_page_env(monkeypatch)
    monkeypatch.setenv("KYNO_PAGE_ACCENT", "")
    monkeypatch.setenv("KYNO_CONSTITUTION_TEMPLATE", "")
    page = Settings.from_env().page
    assert page.theme.accent == "#6d6d66"
    assert page.constitution_template is None


@pytest.mark.parametrize(
    "value",
    ["</style><script>alert(1)</script>", "red; } body { color: red", "@import url(x)", "a\\3c b"],
)
def test_given_a_stylesheet_breaking_theme_value_when_loading_settings_then_it_is_refused(
    monkeypatch, value
):
    # Theme values are written straight into a <style> block, so anything
    # that could close it or start a new rule is refused at startup.
    _clear_page_env(monkeypatch)
    monkeypatch.setenv("KYNO_PAGE_ACCENT", value)
    with pytest.raises(ConfigError, match="KYNO_PAGE_ACCENT"):
        Settings.from_env()
