from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from kyno.errors import ConfigError
from kyno.public_page import PageConfig, PageTheme
from kyno.store.sql import SqlConstitutionStore

# Theme values are written straight into a <style> block, so anything that
# could close it or start a rule of its own is refused rather than escaped.
_UNSAFE_STYLE_VALUE = re.compile(r"[<>{};@\\]")

_THEME_ENV = {
    "accent": "KYNO_PAGE_ACCENT",
    "background": "KYNO_PAGE_BACKGROUND",
    "text": "KYNO_PAGE_TEXT",
    "muted": "KYNO_PAGE_MUTED",
    "rule": "KYNO_PAGE_RULE",
    "font_family": "KYNO_PAGE_FONT",
}


def _page_from_env() -> PageConfig:
    defaults = PageTheme()
    values = {}
    for field_name, env_name in _THEME_ENV.items():
        value = os.environ.get(env_name) or getattr(defaults, field_name)
        if _UNSAFE_STYLE_VALUE.search(value):
            raise ConfigError(
                f"{env_name} contains characters that are not allowed in a style value: {value!r}"
            )
        values[field_name] = value
    return PageConfig(
        theme=PageTheme(**values),
        constitution_template=os.environ.get("KYNO_CONSTITUTION_TEMPLATE") or None,
        index_template=os.environ.get("KYNO_INDEX_TEMPLATE") or None,
    )


# The prefix lands inside DDL identifiers (store/schema.py and the packaged
# migrations), so only a plain identifier fragment is ever accepted.
_TABLE_PREFIX = re.compile(r"[A-Za-z0-9_]+")


def _read_tokens_from_env() -> tuple[str, ...]:
    raw = os.environ.get("KYNO_READ_TOKENS")
    if raw is None:
        return ()
    tokens = tuple(part.strip() for part in raw.split(","))
    if not all(tokens) or not tokens:
        # A blank entry reads as "auth is on" to whoever set it; the only
        # honest answers are working tokens or a loud refusal.
        raise ConfigError("KYNO_READ_TOKENS has a blank entry: give each a value, or unset it")
    return tokens


def _token_from_env() -> str | None:
    token = os.environ.get("KYNO_TOKEN")
    if token is None:
        return None
    if not token.strip():
        # A set-but-blank token reads as "auth is on" to whoever set it; the
        # only honest answers are a working token or a loud refusal.
        raise ConfigError("KYNO_TOKEN is set but blank: give it a value, or unset it")
    return token


def _table_prefix_from_env() -> str:
    prefix = os.environ.get("KYNO_TABLE_PREFIX", "kyno_")
    if not _TABLE_PREFIX.fullmatch(prefix):
        raise ConfigError(
            f"KYNO_TABLE_PREFIX must be letters, digits and underscores, got {prefix!r}"
        )
    return prefix


@dataclass(frozen=True)
class Settings:
    database_url: str
    # repr=False: settings travel into logs and tracebacks; the credential must not.
    token: str | None = field(repr=False)
    table_prefix: str
    host: str
    port: int
    page: PageConfig
    read_tokens: tuple[str, ...] = field(repr=False, default=())

    @classmethod
    def from_env(cls) -> Settings:
        raw_port = os.environ.get("KYNO_PORT", "8080")
        try:
            port = int(raw_port)
        except ValueError:
            raise ConfigError(f"KYNO_PORT must be an integer, got '{raw_port}'") from None
        return cls(
            page=_page_from_env(),
            database_url=os.environ.get("KYNO_DATABASE_URL", "sqlite:///kyno.sqlite3"),
            token=_token_from_env(),
            read_tokens=_read_tokens_from_env(),
            table_prefix=_table_prefix_from_env(),
            host=os.environ.get("KYNO_HOST", "127.0.0.1"),
            port=port,
        )


def store_from_settings(settings: Settings) -> SqlConstitutionStore:
    return SqlConstitutionStore(url=settings.database_url, prefix=settings.table_prefix)
