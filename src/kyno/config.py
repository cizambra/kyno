from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from kyno.errors import ConfigError
from kyno.public_page import PageConfig, PageTheme
from kyno.store.sql import SqlConstitutionStore
from kyno.workspace import find_workspace, read_config

# Theme values are written straight into a <style> block, so anything that
# could close it or start a rule of its own is refused rather than escaped.
_UNSAFE_STYLE_VALUE = re.compile(r"[<>{};@\\]")

_THEME_KEYS = ("accent", "background", "text", "muted", "rule", "font_family")


def _page_from_workspace(page: dict[str, str], root: Path) -> PageConfig:
    defaults = PageTheme()
    values = {}
    for name in _THEME_KEYS:
        value = page.get(name) or getattr(defaults, name)
        if _UNSAFE_STYLE_VALUE.search(value):
            raise ConfigError(
                f"page.{name} contains characters that are not allowed in a style value: {value!r}"
            )
        values[name] = value

    def template(key: str) -> str | None:
        raw = page.get(key)
        if not raw:
            return None
        path = Path(raw)
        # Anchored at the workspace, like the SQLite path: a command run
        # from a subdirectory still finds the same template.
        return str(path if path.is_absolute() else root / path)

    return PageConfig(
        theme=PageTheme(**values),
        constitution_template=template("constitution_template"),
        index_template=template("index_template"),
    )


def _token_from_env() -> str | None:
    token = os.environ.get("KYNO_TOKEN")
    if token is None:
        return None
    if not token.strip():
        # A set-but-blank token reads as "auth is on" to whoever set it; the
        # only honest answers are a working token or a loud refusal.
        raise ConfigError("KYNO_TOKEN is set but blank: give it a value, or unset it")
    return token


@dataclass(frozen=True)
class Settings:
    database_url: str
    # repr=False: settings travel into logs and tracebacks; the credential must not.
    token: str | None = field(repr=False)
    host: str
    port: int
    page: PageConfig
    allow_insecure: bool = False

    @classmethod
    def load(cls) -> Settings:
        """The settings of the workspace at or above the current directory.

        The workspace is the only config surface; the one environment
        variable left is KYNO_TOKEN, and it retires with the tokens
        design."""
        root = find_workspace()
        if root is None:
            raise ConfigError("no workspace here or above; create one with: kyno new NAME")
        ws = read_config(root)
        return cls(
            database_url=ws.database_url,
            token=_token_from_env(),
            host=ws.host,
            port=ws.port,
            page=_page_from_workspace(ws.page, ws.root),
            allow_insecure=ws.allow_insecure,
        )


def store_from_settings(settings: Settings) -> SqlConstitutionStore:
    return SqlConstitutionStore(url=settings.database_url)
