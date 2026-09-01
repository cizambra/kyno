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
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

from kyno.coerce import to_bool as _bool
from kyno.coerce import to_int as _int
from kyno.envref import resolve as _resolve_ref
from kyno.errors import ConfigError

CONFIG_RELPATH = Path("config") / "server"

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

# 2256 is CALM on a phone keypad, the way 6379 is MERZ to Redis: a port
# with a story, instead of another squatter on 8080.
_CONFIG_TEMPLATE = """\
# This Kyno's definition. Values are written in, or are ${VAR} references
# to variables you name. Secrets only ever enter as references.

[server]
host = 127.0.0.1
port = 2256

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
    """What config/server says, checked and resolved.

    Anything that doesn't resolve fails loudly and names the fix: an
    unknown key is a typo, an unset ${VAR} is a missing export. Stopping
    at startup beats serving half-configured."""
    parser = _parse(root / CONFIG_RELPATH)
    host, port, allow_insecure = _server_values(parser)
    database = dict(parser["database"]) if parser.has_section("database") else {}
    return WorkspaceConfig(
        root=root,
        database_url=_database_url(database, root),
        host=host,
        port=port,
        allow_insecure=allow_insecure,
        page=_page_values(parser),
    )


def _parse(config_path: Path) -> configparser.ConfigParser:
    """The INI itself, with every section and key checked for typos."""
    parser = configparser.ConfigParser(interpolation=None)
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
    return parser


def _server_values(parser: configparser.ConfigParser) -> tuple[str, int, bool]:
    server = parser["server"] if parser.has_section("server") else {}
    host = _resolve_ref(server.get("host", "127.0.0.1"), owner="server.host")
    port = _int(_resolve_ref(server.get("port", "2256"), owner="server.port"), owner="server.port")
    allow_insecure = _bool(
        _resolve_ref(server.get("allow_insecure", "false"), owner="server.allow_insecure"),
        owner="server.allow_insecure",
    )
    return host, port, allow_insecure


def _page_values(parser: configparser.ConfigParser) -> dict[str, str]:
    if not parser.has_section("page"):
        return {}
    return {key: _resolve_ref(value, owner=f"page.{key}") for key, value in parser["page"].items()}


def _database_url(values: dict, root: Path) -> str:
    """One URL out of [database], whichever shape the section took."""
    url = values.get("url")
    if url is not None and any(k != "url" for k in values):
        raise ConfigError(
            "pick one: url carries the whole connection; "
            "the split database keys describe it piece by piece"
        )
    if url is not None:
        return _resolve_ref(url, owner="database.url")
    adapter = _resolve_ref(values.get("adapter", "sqlite3"), owner="database.adapter")
    if adapter not in _ADAPTERS:
        raise ConfigError(f"unknown adapter '{adapter}': one of {', '.join(sorted(_ADAPTERS))}")
    if adapter == "sqlite3":
        return _sqlite_url(values, root)
    return _postgres_url(values, adapter)


def _sqlite_url(values: dict, root: Path) -> str:
    raw = _resolve_ref(values.get("database", "db/kyno.sqlite3"), owner="database.database")
    path = Path(raw)
    if not path.is_absolute():
        # Anchored at the workspace, so a command run from a
        # subdirectory still finds the same store.
        path = root / path
    return f"sqlite:///{path}"


def _postgres_url(values: dict, adapter: str) -> str:
    database = values.get("database")
    if not database:
        raise ConfigError("database.database is required for postgresql")
    host = _resolve_ref(values.get("host", "localhost"), owner="database.host")
    port = values.get("port")
    userinfo = ""
    username = values.get("username")
    password = values.get("password")
    if username:
        userinfo = quote(_resolve_ref(username, owner="database.username"), safe="")
        if password:
            userinfo += ":" + quote(_resolve_ref(password, owner="database.password"), safe="")
        userinfo += "@"
    if port is None:
        hostport = host
    else:
        resolved = _resolve_ref(port, owner="database.port")
        hostport = f"{host}:{_int(resolved, owner='database.port')}"
    name = quote(_resolve_ref(database, owner="database.database"), safe="")
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
