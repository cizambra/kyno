"""Helpers for driving MCP-over-HTTP requests in tests: a store with
minted tokens, the headers, and a full initialize/notify/call session."""

from kyno.store.sql import SqlConstitutionStore
from kyno.tokens import generate_value, hash_value

MCP_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}


def token_store():
    """A created in-memory store, ready to hold tokens."""
    store = SqlConstitutionStore(url="sqlite://")
    store.create_all()
    return store


def mint(store, scope="write", name="t", expires_at=None):
    """Mint a token into the store and return the value a client would hold."""
    value = generate_value()
    store.add_token(name, scope, token_hash=hash_value(value), expires_at=expires_at)
    return value


def bearer(value):
    """The MCP headers plus the Authorization header for this token value."""
    return {**MCP_HEADERS, "Authorization": f"Bearer {value}"}


def initialize_payload():
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "0.0"},
        },
    }


def drive_session(client, headers):
    """Initialize and confirm an MCP session; returns the headers to use
    for the session's tool calls."""
    init_resp = client.post("/mcp", json=initialize_payload(), headers=headers)
    session_id = init_resp.headers["mcp-session-id"]
    h = {**headers, "mcp-session-id": session_id}
    client.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers=h)
    return h


def call_tool(client, headers, request_id, name, arguments):
    return client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
        headers=headers,
    )


def sse_json(text):
    """The JSON payload inside a server-sent-events response body."""
    import json

    for line in text.splitlines():
        if line.startswith("data: "):
            return json.loads(line[len("data: ") :])
    raise AssertionError(f"no data: line in the server-sent-events body: {text!r}")
