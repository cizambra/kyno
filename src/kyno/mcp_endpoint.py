"""The MCP endpoint served at /mcp: the token check, the size cap, the
read/write rule, and the hand-off to the MCP session manager.

kyno.transports builds the HTTP app and mounts McpEndpoint at /mcp next to
the public constitution pages.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta

from kyno.mcp_tools import TOOL_SCOPES
from kyno.models import WRITE, Token
from kyno.tokens import hash_value

# A JSON-RPC request is small. The largest legitimate one carries a full constitution, and the
# field size limits keep that well under this cap.
MAX_MCP_BODY_BYTES = 5_000_000

# One line per tool call: token id and name, the tool, and the constitution.
# Read this log to know what a token did and when.
_request_log = logging.getLogger("kyno.requests")

# How often last_used_at is allowed to move. A token already marked as used
# in the last five minutes is not updated again, so a busy fleet costs one
# write per token every five minutes instead of one per request. In exchange,
# "last used" in `kyno token list` can run up to five minutes behind.
TOUCH_EVERY = timedelta(minutes=5)


def _tool_calls(body: bytes) -> list[tuple[str, str]]:
    """List the (tool, constitution) pairs a JSON-RPC body asks for.

    Returns an empty list for a body that is not valid JSON, or that
    carries no tool call: rejecting malformed requests is the MCP layer's
    job, and this only reports what it can read.

    A JSON array (a batch) is read too, one pair per item. Batches are
    NOT supported. Do not build batch APIs on this: they will error, the
    MCP layer rejects arrays. The scope check reads the shape anyway so
    that a future SDK version that accepts batches cannot become a way
    past the read/write rule."""
    try:
        payload = json.loads(body)
    except ValueError:
        return []
    items = payload if isinstance(payload, list) else [payload]
    calls = []
    for item in items:
        if not isinstance(item, dict) or item.get("method") != "tools/call":
            continue
        params = item.get("params") or {}
        arguments = params.get("arguments") or {}
        name = params.get("name")
        if isinstance(name, str):
            calls.append((name, arguments.get("constitution") or "default"))
    return calls


def _decoded_headers(scope) -> dict:
    """The request headers as text. ASGI hands them over as bytes; values
    that are not valid UTF-8 are decoded with replacement characters, so a
    broken header can never crash the request."""
    return {
        k.decode(errors="replace"): v.decode(errors="replace") for k, v in scope.get("headers", [])
    }


def _body_declared_over_cap(headers: dict) -> bool:
    """True when the Content-Length header announces a body over the cap.
    Answering here avoids reading a body we would refuse anyway; a chunked
    request declares no length and is counted while it streams instead."""
    declared = headers.get("content-length", "")
    return declared.isdigit() and int(declared) > MAX_MCP_BODY_BYTES


def _refusal(token, calls) -> str | None:
    """The 403 message for a request the token may not make, or None when
    every requested call is allowed. With the check off (token is None),
    nothing is refused.

    Every tool must appear in TOOL_SCOPES with the scope it requires. A
    tool that is not in the map is denied even for a write token: an
    undeclared tool fails closed instead of defaulting to allowed. The two
    denials read differently on purpose: a scope problem blames the token,
    an undeclared tool is named as unknown."""
    if token is None:
        return None
    for name, _ in calls:
        required = TOOL_SCOPES.get(name)
        if required is None:
            return f"unknown tool: '{name}' does not exist"
        if required == WRITE and token.scope != WRITE:
            return f"forbidden: this token's scope does not cover '{name}'"
    return None


class McpEndpoint:
    """The ASGI app served at /mcp. On every request it checks the token,
    enforces the body size cap, applies the read/write rule, and only then
    hands the request to the MCP session manager.

    One instance serves every request; nothing request-specific is stored
    on self."""

    def __init__(self, manager, token_store):
        self._manager = manager
        self._token_store = token_store

    def _authenticate(self, headers) -> Token | None:
        """Find the live token the request's bearer header carries, or None.

        Returns None in four cases: no Authorization header, a header that
        is not a Bearer value, a value no row matches, and a token that is
        revoked or expired. The caller turns None into a 401.

        The four cases return the same response on purpose. Distinguishing
        them would tell a caller which tokens exist."""
        value = None
        for k, v in headers.items():
            if k.lower() == "authorization":
                value = v
                break
        if value is None or not value.startswith("Bearer "):
            return None
        token = self._token_store.token_by_hash(hash_value(value[len("Bearer ") :]))
        if token is None or not token.live_at(datetime.now(UTC)):
            return None
        return token

    async def __call__(self, scope, receive, send):
        from starlette.responses import Response

        headers = _decoded_headers(scope)
        token = None
        if self._token_store is not None:
            token = self._authenticate(headers)
            if token is None:
                await Response("unauthorized", status_code=401)(scope, receive, send)
                return
            self._token_store.touch_token(token.id, older_than=datetime.now(UTC) - TOUCH_EVERY)
        if _body_declared_over_cap(headers):
            await Response("request body too large", status_code=413)(scope, receive, send)
            return
        if scope.get("method") != "POST":
            # GET opens the server-sent-events stream, where the server
            # pushes notifications; DELETE closes a session. Neither
            # carries a tool call, so there is no scope to check and
            # nothing to log.
            await self._manager.handle_request(scope, receive, send)
            return
        body = await self._read_body(scope, receive, send)
        if body is None:
            return
        calls = _tool_calls(body)
        refusal = _refusal(token, calls)
        if refusal is not None:
            await Response(refusal, status_code=403)(scope, receive, send)
            return
        if token is not None:
            for name, constitution in calls:
                _request_log.info(
                    "token=%s name=%s tool=%s constitution=%s",
                    token.id,
                    token.name,
                    name,
                    constitution,
                )
        await self._manager.handle_request(scope, _replayed(body, receive), send)

    async def _read_body(self, scope, receive, send) -> bytes | None:
        """Buffer the whole request body and return it, or return None
        after answering when the request cannot proceed.

        The body is buffered because the size cap needs the byte count and
        the read/write rule needs to see the tool name before the MCP
        layer runs. None means either the client disconnected mid-body
        (nothing was sent back) or the body crossed the size cap (a 413
        was sent).

        Each receive() returns one ASGI message. For a request body it is
        {"type": "http.request", "body": bytes, "more_body": bool}; any
        other type here means the client disconnected."""
        from starlette.responses import Response

        body = bytearray()
        while True:
            message = await receive()
            if message["type"] != "http.request":
                return None
            body.extend(message.get("body") or b"")
            if len(body) > MAX_MCP_BODY_BYTES:
                await Response("request body too large", status_code=413)(scope, receive, send)
                return None
            if not message.get("more_body"):
                break
        return bytes(body)


def _replayed(body: bytes, receive):
    """A receive callable that hands the MCP layer the buffered body first,
    then continues with the real channel (disconnect messages and so on)."""
    delivered = False

    async def replay():
        nonlocal delivered
        if not delivered:
            delivered = True
            return {"type": "http.request", "body": body, "more_body": False}
        return await receive()

    return replay
