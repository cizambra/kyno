"""How Kyno serves: the startup checks and the two transports.

serve_stdio runs the MCP server on stdin/stdout. serve_http checks the
token table and hands the app to uvicorn. The CLI's `kyno serve` command
parses arguments, calls one of these two functions, and prints any
ConfigError they raise.
"""

from __future__ import annotations

import logging
import sys
import time
from datetime import UTC, datetime

from sqlalchemy.exc import SQLAlchemyError

from kyno.config import Settings
from kyno.errors import ConfigError
from kyno.service import ControlPlane


def serve_stdio(control_plane: ControlPlane) -> None:
    """Run the MCP server over stdin/stdout until the client disconnects."""
    import anyio

    from kyno.transports import run_stdio

    anyio.run(run_stdio, control_plane)


def serve_http(settings: Settings, store, control_plane: ControlPlane) -> None:
    """Serve HTTP: check the token table, then hand the app to uvicorn.

    The CLI calls this with the loaded workspace settings and the store
    those settings point at.

    Raises ConfigError when the database has no token table; the fix is
    `kyno db upgrade`. An empty token table is different: the server
    starts, every /mcp request is refused until a token is minted, and a
    note on stderr explains that. With allow_insecure on, none of this
    applies: the app is built without a token store, nothing is checked,
    and a warning goes to stderr."""
    if settings.allow_insecure:
        print(
            "WARNING: serving HTTP without token checks (allow_insecure is on) "
            "— the constitution can be rewritten by anyone who can reach this "
            "endpoint",
            file=sys.stderr,
        )
    else:
        _note_when_tokenless(store)
    _configure_request_log()
    import uvicorn

    from kyno.transports import build_http_app

    uvicorn.run(
        build_http_app(
            control_plane,
            token_store=None if settings.allow_insecure else store,
            page=settings.page,
            allow_insecure=settings.allow_insecure,
        ),
        host=settings.host,
        port=settings.port,
    )


def _configure_request_log() -> None:
    """Give the kyno.requests logger a stderr handler with UTC timestamps.

    The transports module writes one line per tool call to this logger;
    without a handler those lines would be dropped, because uvicorn only
    configures its own loggers."""
    handler = logging.StreamHandler()
    formatter = logging.Formatter("%(asctime)s %(message)s", datefmt="%Y-%m-%dT%H:%M:%SZ")
    formatter.converter = time.gmtime
    handler.setFormatter(formatter)
    request_log = logging.getLogger("kyno.requests")
    request_log.addHandler(handler)
    request_log.setLevel(logging.INFO)
    request_log.propagate = False


def _note_when_tokenless(store) -> None:
    """Check the token table before serving: raise ConfigError when the
    table is missing (an old database, fixed by `kyno db upgrade`), and
    print a note to stderr when it holds no live token.

    serve_http calls this once at startup. An empty table is safe to
    serve: every /mcp request is answered 401 until a token exists, so
    an operator can start the server first and mint tokens later. The
    endpoint checks the database on every request, so a token minted
    while the server runs works without a restart."""
    try:
        tokens = store.tokens()
    except SQLAlchemyError:
        raise ConfigError("the database has no token table yet; run: kyno db upgrade") from None
    now = datetime.now(UTC)
    if not any(t.live_at(now) for t in tokens):
        print(
            "note: no live tokens yet, so every /mcp request will be refused "
            "(401) until one is minted: kyno token add NAME --scope read",
            file=sys.stderr,
        )
