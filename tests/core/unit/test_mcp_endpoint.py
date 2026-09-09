from datetime import UTC, datetime, timedelta

import pytest

from kyno.mcp_endpoint import McpEndpoint, _tool_calls
from tests.mcp_requests import mint, token_store


def _endpoint(store):
    return McpEndpoint(manager=None, token_store=store)


def test_given_a_request_with_no_authorization_header_when_resolving_then_no_token_is_found():
    assert _endpoint(token_store())._authenticate({}) is None


def test_given_a_live_token_when_resolving_then_the_row_comes_back_with_its_scope():
    store = token_store()
    value = mint(store, scope="read", name="crew")

    token = _endpoint(store)._authenticate({"authorization": f"Bearer {value}"})

    assert token is not None
    assert (token.name, token.scope) == ("crew", "read")


def test_given_a_capitalized_authorization_header_when_resolving_then_it_still_matches():
    store = token_store()
    value = mint(store)
    assert _endpoint(store)._authenticate({"Authorization": f"Bearer {value}"}) is not None


def test_given_a_token_that_is_unknown_revoked_or_expired_when_resolving_then_it_is_none():
    store = token_store()
    revoked_value = mint(store, name="revoked")
    store.revoke_token(store.tokens()[0].id)
    expired_value = mint(store, name="expired", expires_at=datetime.now(UTC) - timedelta(hours=1))

    for value in ("kyno_not-a-real-token", revoked_value, expired_value):
        assert _endpoint(store)._authenticate({"authorization": f"Bearer {value}"}) is None


def test_given_an_authorization_header_that_is_not_a_bearer_value_when_resolving_then_none():
    store = token_store()
    mint(store)
    assert _endpoint(store)._authenticate({"authorization": "Basic dXNlcjpwdw=="}) is None


def test_given_a_non_ascii_bearer_value_when_resolving_then_it_fails_closed_not_crashes():
    assert _endpoint(token_store())._authenticate({"authorization": "Bearer café"}) is None


def test_given_bodies_of_every_shape_when_listing_tool_calls_then_only_real_calls_count():
    assert _tool_calls(b"not json") == []
    assert _tool_calls(b'{"method": "initialize"}') == []
    assert _tool_calls(
        b'{"method": "tools/call", "params": {"name": "set_direction", "arguments": {}}}'
    ) == [("set_direction", "default")]
    # A batch (JSON array) is read by this check, one pair per item, in
    # order -- but the MCP SDK rejects arrays, so a batch never executes.
    # The HTTP behavior is covered by the batched-body integration test.
    assert _tool_calls(
        b'[{"method": "tools/call", "params": {"name": "get_constitution", '
        b'"arguments": {"constitution": "main"}}},'
        b'{"method": "notifications/initialized"},'
        b'{"method": "tools/call", "params": {"name": "set_direction", '
        b'"arguments": {"mission": "M1"}}}]'
    ) == [("get_constitution", "main"), ("set_direction", "default")]


@pytest.mark.asyncio
async def test_given_non_utf8_header_bytes_when_handling_the_request_then_it_is_401_not_500():
    # A header value that isn't valid UTF-8 at all (not just non-ASCII) must
    # not crash v.decode() in handle(); it should fail closed as 401.
    handle = _endpoint(token_store())

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/",
        "headers": [(b"authorization", b"Bearer \xff\xfe-not-utf8")],
    }

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    sent = []

    async def send(message):
        sent.append(message)

    await handle(scope, receive, send)
    status = next(m["status"] for m in sent if m["type"] == "http.response.start")
    assert status == 401


@pytest.mark.asyncio
async def test_given_a_disconnect_mid_body_when_reading_then_nothing_is_sent_back():
    # The client hung up while sending: the endpoint stops and sends no
    # response at all, instead of answering a half-received request.
    store = token_store()
    value = mint(store)
    endpoint = McpEndpoint(manager=None, token_store=store)

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/",
        "headers": [(b"authorization", f"Bearer {value}".encode())],
    }
    messages = [
        {"type": "http.request", "body": b'{"partial', "more_body": True},
        {"type": "http.disconnect"},
    ]

    async def receive():
        return messages.pop(0)

    sent = []

    async def send(message):
        sent.append(message)

    await endpoint(scope, receive, send)
    assert sent == []


def test_given_the_declarations_when_projecting_them_then_no_two_tools_share_a_name():
    # TOOLS and TOOL_SCOPES are projections of one declaration list, so
    # they cannot drift apart. The one way the projections can lie is a
    # duplicate tool name, which would silently overwrite its twin in the
    # scope map.
    from kyno.mcp_tools import TOOL_SCOPES, TOOLS

    assert len(TOOLS) == len(TOOL_SCOPES)


def test_given_tool_declarations_when_reading_scopes_then_every_scope_is_typed():
    from kyno.mcp_tools import TOOL_SCOPES
    from kyno.models import TokenScope

    assert all(type(scope) is TokenScope for scope in TOOL_SCOPES.values())
    assert TOOL_SCOPES["set_direction"] is TokenScope.WRITE
