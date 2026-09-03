"""How Kyno serves: the startup checks and the two transports.

serve_stdio runs the MCP server on stdin/stdout. serve_http checks the
token table and hands the app to uvicorn. The CLI's `kyno serve` command
parses arguments, calls one of these two functions, and prints any
ConfigError they raise.
"""

from __future__ import annotations

import sys
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

    Raises ConfigError in two cases: the database has no token table (the
    fix is `kyno db upgrade`), and no live token exists (the fix is minting
    one, or allow_insecure in config/server). With allow_insecure on, both
    checks are skipped, the app is built without a store, and a warning
    goes to stderr."""
    if settings.allow_insecure:
        print(
            "WARNING: serving HTTP without token checks (allow_insecure is on) "
            "— the constitution can be rewritten by anyone who can reach this "
            "endpoint",
            file=sys.stderr,
        )
    else:
        _require_live_tokens(store)
    import uvicorn

    from kyno.transports import build_http_app

    uvicorn.run(
        build_http_app(
            control_plane,
            store=None if settings.allow_insecure else store,
            page=settings.page,
            allow_insecure=settings.allow_insecure,
        ),
        host=settings.host,
        port=settings.port,
    )


def _require_live_tokens(store) -> None:
    """Refuse to open the write endpoint by accident: raise ConfigError when
    the token table is missing (an old database) or holds no live token."""
    try:
        tokens = store.tokens()
    except SQLAlchemyError:
        raise ConfigError("the database has no token table yet; run: kyno db upgrade") from None
    now = datetime.now(UTC)
    if not any(t.live_at(now) for t in tokens):
        raise ConfigError(
            "refusing to serve HTTP with no live tokens: mint one with: "
            "kyno token add NAME --scope write, or set allow_insecure = true "
            "in config/server to override for local use"
        )
