"""The workspace: the directory that defines one Kyno instance.

`kyno new` creates it, and every command that needs the store finds it by
walking up from where you stand, like git does. The files under ~/.kyno
stay user-bound -- credentials and remotes travel with a person. The
workspace is the organization's instance definition, so it lives in a
directory that can be committed and mounted; secrets only ever enter it
as ${VAR} references to variables the operator named.
"""

from __future__ import annotations

import configparser
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

from kyno.errors import ConfigError

CONFIG_RELPATH = Path("config") / "server"

_ENV_REF = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$")

# adapter key -> the SQLAlchemy dialect (and driver) it stands for
_ADAPTERS = {"sqlite3": "sqlite", "postgresql": "postgresql+psycopg"}

_SERVER_KEYS = ("host", "port", "allow_insecure")
_DATABASE_KEYS = ("url", "adapter", "host", "port", "database", "username", "password")
_PAGE_KEYS = (
    "accent",
    "background",
    "text",
    "muted",
    "rule",
    "font_family",
    "constitution_template",
    "index_template",
)

_CONFIG_TEMPLATE = """\
# This Kyno's definition. Values are written in, or are ${VAR} references
# to variables you name. Secrets only ever enter as references.

[server]
host = 127.0.0.1
port = 8080

[database]
adapter = sqlite3
database = db/kyno.sqlite3
"""

_GITIGNORE_TEMPLATE = """\
# The store is data, not definition.
db/*.sqlite3
"""

_README_TEMPLATE = """\
# {name}

This directory is a Kyno instance: its configuration and, on SQLite,
its store. The direction itself lives in your team's repo and arrives
over the wire.

    kyno init-db                 create the store
    kyno serve --transport http  serve it
"""


@dataclass(frozen=True)
class WorkspaceConfig:
    root: Path
    # repr=False: the URL may carry a password, and configs travel into logs.
    database_url: str = field(repr=False)
    host: str
    port: int
    allow_insecure: bool
    page: dict[str, str]


def find_workspace(start: Path | None = None) -> Path | None:
    """The nearest directory at or above `start` holding config/server."""
    here = (start or Path.cwd()).resolve()
    for candidate in (here, *here.parents):
        if (candidate / CONFIG_RELPATH).is_file():
            return candidate
    return None


def create_workspace(path: Path) -> Path:
    """Write the four files a fresh workspace is made of."""
    if (path / CONFIG_RELPATH).is_file():
        raise ConfigError(f"'{path}' is already a workspace")
    (path / "config").mkdir(parents=True, exist_ok=True)
    (path / "db").mkdir(exist_ok=True)
    (path / CONFIG_RELPATH).write_text(_CONFIG_TEMPLATE, encoding="utf-8")
    (path / ".gitignore").write_text(_GITIGNORE_TEMPLATE, encoding="utf-8")
    (path / "README.md").write_text(
        _README_TEMPLATE.format(name=path.name or "kyno"), encoding="utf-8"
    )
    (path / "db" / ".keep").write_text("", encoding="utf-8")
    return path


def read_config(root: Path) -> WorkspaceConfig:
    """The workspace's config/server, checked and resolved.

    Anything that doesn't resolve fails loudly and names the fix: an
    unknown key is a typo, an unset ${VAR} is a missing export, and both
    are better caught at startup than discovered as a half-configured
    server."""
    parser = configparser.ConfigParser(interpolation=None)
    config_path = root / CONFIG_RELPATH
    try:
        with open(config_path, encoding="utf-8") as handle:
            parser.read_file(handle)
    except OSError as exc:
        raise ConfigError(f"cannot read {config_path}: {exc.strerror or exc}") from None
    except configparser.Error as exc:
        raise ConfigError(f"{config_path} is not valid INI: {exc}") from None

    for section in parser.sections():
        if section not in ("server", "database", "page"):
            raise ConfigError(
                f"unknown section [{section}] in {config_path}; "
                "the sections are [server], [database] and [page]"
            )
    _check_keys(parser, "server", _SERVER_KEYS, config_path)
    _check_keys(parser, "database", _DATABASE_KEYS, config_path)
    _check_keys(parser, "page", _PAGE_KEYS, config_path)

    server = parser["server"] if parser.has_section("server") else {}
    host = _resolve(server.get("host", "127.0.0.1"), key="server.host")
    port = _int(_resolve(server.get("port", "8080"), key="server.port"), key="server.port")
    allow_insecure = _bool(
        _resolve(server.get("allow_insecure", "false"), key="server.allow_insecure"),
        key="server.allow_insecure",
    )

    database = dict(parser["database"]) if parser.has_section("database") else {}
    database_url = _database_url(database, root)

    page = {}
    if parser.has_section("page"):
        for key, value in parser["page"].items():
            page[key] = _resolve(value, key=f"page.{key}")

    return WorkspaceConfig(
        root=root,
        database_url=database_url,
        host=host,
        port=port,
        allow_insecure=allow_insecure,
        page=page,
    )


def _database_url(values: dict, root: Path) -> str:
    url = values.get("url")
    split_keys = [k for k in values if k != "url"]
    if url is not None and split_keys:
        raise ConfigError(
            "pick one: url carries the whole connection; "
            "the split database keys describe it piece by piece"
        )
    if url is not None:
        return _resolve(url, key="database.url")

    adapter = _resolve(values.get("adapter", "sqlite3"), key="database.adapter")
    if adapter not in _ADAPTERS:
        raise ConfigError(f"unknown adapter '{adapter}': one of {', '.join(sorted(_ADAPTERS))}")
    if adapter == "sqlite3":
        raw = _resolve(values.get("database", "db/kyno.sqlite3"), key="database.database")
        path = Path(raw)
        if not path.is_absolute():
            # Anchored at the workspace, so a command run from a
            # subdirectory still finds the same store.
            path = root / path
        return f"sqlite:///{path}"

    database = values.get("database")
    if not database:
        raise ConfigError("database.database is required for postgresql")
    host = _resolve(values.get("host", "localhost"), key="database.host")
    port = values.get("port")
    userinfo = ""
    username = values.get("username")
    password = values.get("password")
    if username:
        userinfo = quote(_resolve(username, key="database.username"), safe="")
        if password:
            userinfo += ":" + quote(_resolve(password, key="database.password"), safe="")
        userinfo += "@"
    if port is None:
        hostport = host
    else:
        hostport = f"{host}:{_int(_resolve(port, key='database.port'), key='database.port')}"
    name = quote(_resolve(database, key="database.database"), safe="")
    return f"{_ADAPTERS[adapter]}://{userinfo}{hostport}/{name}"


def _check_keys(parser, section: str, allowed: tuple, config_path: Path) -> None:
    if not parser.has_section(section):
        return
    for key in parser[section]:
        if key not in allowed:
            raise ConfigError(
                f"unknown key '{key}' in [{section}] of {config_path}; "
                f"the keys are: {', '.join(allowed)}"
            )


def _resolve(value: str, *, key: str) -> str:
    match = _ENV_REF.match(value.strip())
    if match is None:
        return value.strip()
    var = match.group(1)
    got = os.environ.get(var)
    if got is None:
        raise ConfigError(f"{key} reads ${{{var}}}, which is not set")
    if not got.strip():
        raise ConfigError(f"{key} reads ${{{var}}}, which is blank")
    return got


def _int(value: str, *, key: str) -> int:
    try:
        return int(value)
    except ValueError:
        raise ConfigError(f"{key} must be an integer, got '{value}'") from None


def _bool(value: str, *, key: str) -> bool:
    lowered = value.lower()
    if lowered in ("true", "1", "yes"):
        return True
    if lowered in ("false", "0", "no"):
        return False
    raise ConfigError(f"{key} must be true or false, got '{value}'")
