"""MCP client sessions through the built server."""

import asyncio
import json

import mcp.types as types
import pytest

from kyno import mcp_server
from kyno.service import ControlPlane
from kyno.store.sql import SqlConstitutionStore


def _sse_json_body(response_text: str) -> dict:
    # The streamable-HTTP transport returns SSE-framed responses:
    # "event: message\ndata: {...}\n\n". Pull the JSON payload out.
    for line in response_text.splitlines():
        if line.startswith("data: "):
            return json.loads(line[len("data: ") :])
    raise AssertionError(f"no data: line in SSE body: {response_text!r}")


RICH = dict(
    mission="Ship trustworthy lending",
    declaration="# Our declaration\n\nThe long form of what that means.",
    principles=[{"title": "Be honest", "description": "Say the hard number first."}],
)


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_given_a_real_subscription_when_setting_direction_then_the_server_run_notifies():
    # Unlike test_version_bump_notifies_subscribed_session (FakeSession injected
    # directly), this drives the real subscribe handler and server.run().
    from mcp.shared.memory import create_connected_server_and_client_session

    store = SqlConstitutionStore(url="sqlite://")
    store.create_all()
    cp = ControlPlane(store)
    server = mcp_server.build_server(cp)

    received = []

    async def message_handler(message):
        if isinstance(message, types.ServerNotification) and isinstance(
            message.root, types.ResourceUpdatedNotification
        ):
            received.append(str(message.root.params.uri))

    async with create_connected_server_and_client_session(
        server, message_handler=message_handler
    ) as client:
        await client.subscribe_resource(mcp_server.RESOURCE_URI)
        await client.call_tool("set_direction", {"mission": "M1", "change_note": "init"})
        await asyncio.gather(*server._kyno_pending)

    assert received == [mcp_server.RESOURCE_URI]


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_given_a_non_matching_uri_when_subscribing_then_it_is_a_noop():
    from mcp.shared.memory import create_connected_server_and_client_session

    store = SqlConstitutionStore(url="sqlite://")
    store.create_all()
    cp = ControlPlane(store)
    server = mcp_server.build_server(cp)

    async with create_connected_server_and_client_session(server) as client:
        await client.subscribe_resource("kyno://something-else")
        assert server._kyno_subscribers == set()


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_given_a_subscribed_session_when_unsubscribing_for_real_then_it_is_removed():
    from mcp.shared.memory import create_connected_server_and_client_session

    store = SqlConstitutionStore(url="sqlite://")
    store.create_all()
    cp = ControlPlane(store)
    server = mcp_server.build_server(cp)

    async with create_connected_server_and_client_session(server) as client:
        await client.subscribe_resource(mcp_server.RESOURCE_URI)
        assert len(server._kyno_subscribers) == 1
        await client.unsubscribe_resource(mcp_server.RESOURCE_URI)
        assert server._kyno_subscribers == set()


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_given_an_unknown_tool_name_when_dispatching_then_the_mcp_error_is_clean():
    from mcp.shared.memory import create_connected_server_and_client_session

    store = SqlConstitutionStore(url="sqlite://")
    store.create_all()
    cp = ControlPlane(store)
    server = mcp_server.build_server(cp)

    async with create_connected_server_and_client_session(server) as client:
        result = await client.call_tool("no_such_tool", {})
        assert result.isError is True


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_given_an_unknown_resource_uri_when_dispatching_then_the_mcp_error_is_clean():
    from mcp.shared.exceptions import McpError
    from mcp.shared.memory import create_connected_server_and_client_session

    store = SqlConstitutionStore(url="sqlite://")
    store.create_all()
    cp = ControlPlane(store)
    server = mcp_server.build_server(cp)

    async with create_connected_server_and_client_session(server) as client:
        with pytest.raises(McpError):
            await client.read_resource("kyno://no-such-resource")


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_given_a_non_integer_version_when_calling_get_changes_since_then_the_error_is_clean():
    from mcp.shared.memory import create_connected_server_and_client_session

    store = SqlConstitutionStore(url="sqlite://")
    store.create_all()
    cp = ControlPlane(store)
    cp.set_direction(mission="M1", change_note="init")
    server = mcp_server.build_server(cp)

    async with create_connected_server_and_client_session(server) as client:
        result = await client.call_tool("get_changes_since", {"known_version": "abc"})
        assert result.isError is True


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_given_stdio_and_http_sessions_when_getting_the_constitution_then_they_match():
    # Both transports share build_server()/ControlPlane underneath, so this
    # compares the in-memory harness against the real HTTP transport for the same version.
    from mcp.shared.memory import create_connected_server_and_client_session

    store = SqlConstitutionStore(url="sqlite://")
    store.create_all()
    cp = ControlPlane(store)
    cp.set_direction(mission="M1", principles=["p1"], change_note="init", created_by="op")
    server = mcp_server.build_server(cp)

    async with create_connected_server_and_client_session(server) as client:
        res = await client.call_tool("get_constitution", {})
        session_payload = json.loads(res.content[0].text)

    from starlette.testclient import TestClient

    from kyno.transports import build_http_app

    http_headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }
    http_app = build_http_app(cp, allow_insecure=True)
    with TestClient(http_app) as client:
        init_resp = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "t", "version": "0"},
                },
            },
            headers=http_headers,
        )
        session_id = init_resp.headers["mcp-session-id"]
        h = {**http_headers, "mcp-session-id": session_id}
        client.post(
            "/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers=h
        )
        tool_resp = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "get_constitution", "arguments": {}},
            },
            headers=h,
        )

    http_payload = json.loads(_sse_json_body(tool_resp.text)["result"]["content"][0]["text"])
    assert session_payload == http_payload


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_given_a_fresh_store_when_getting_the_constitution_for_real_then_it_answers():
    # Unlike test_get_constitution_on_fresh_store_returns_empty_state (handler
    # called directly), this drives the real call_tool dispatch end to end.
    from mcp.shared.memory import create_connected_server_and_client_session

    store = SqlConstitutionStore(url="sqlite://")
    store.create_all()
    cp = ControlPlane(store)
    server = mcp_server.build_server(cp)

    async with create_connected_server_and_client_session(server) as client:
        res = await client.call_tool("get_constitution", {})
        payload = json.loads(res.content[0].text)

    assert payload["version"] == 0
    assert payload["mission"] == ""
    assert payload["principles"] == []


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_given_a_fresh_store_when_reading_the_resource_then_the_empty_state_returns():
    from mcp.shared.memory import create_connected_server_and_client_session

    store = SqlConstitutionStore(url="sqlite://")
    store.create_all()
    cp = ControlPlane(store)
    server = mcp_server.build_server(cp)

    async with create_connected_server_and_client_session(server) as client:
        result = await client.read_resource(mcp_server.RESOURCE_URI)
        payload = json.loads(result.contents[0].text)

    assert payload["version"] == 0


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_given_named_constitutions_when_dispatching_writes_then_sequences_are_independent():
    from mcp.shared.memory import create_connected_server_and_client_session

    store = SqlConstitutionStore(url="sqlite://")
    store.create_all()
    cp = ControlPlane(store)
    server = mcp_server.build_server(cp)

    async with create_connected_server_and_client_session(server) as client:
        await client.call_tool("set_direction", {"mission": "M1", "change_note": "init"})
        await client.call_tool(
            "set_direction", {"mission": "EU1", "change_note": "init", "constitution": "eu"}
        )
        await client.call_tool(
            "set_direction", {"mission": "EU2", "change_note": "pivot", "constitution": "eu"}
        )
        default = json.loads((await client.call_tool("get_constitution", {})).content[0].text)
        eu = json.loads(
            (await client.call_tool("get_constitution", {"constitution": "eu"})).content[0].text
        )

    assert default["version"] == 1 and default["mission"] == "M1"
    assert eu["version"] == 2 and eu["mission"] == "EU2"


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_given_a_named_write_when_reading_the_resource_then_it_stays_the_default():
    from mcp.shared.memory import create_connected_server_and_client_session

    store = SqlConstitutionStore(url="sqlite://")
    store.create_all()
    cp = ControlPlane(store)
    cp.set_direction(mission="M1", change_note="init")
    cp.set_direction(mission="EU1", change_note="eu init", constitution="eu")
    server = mcp_server.build_server(cp)

    async with create_connected_server_and_client_session(server) as client:
        result = await client.read_resource(mcp_server.RESOURCE_URI)
        payload = json.loads(result.contents[0].text)

    assert payload["mission"] == "M1"


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_given_the_subscribable_resource_when_reading_then_it_serves_the_compact_form():
    # A resource takes no parameters, and it is the thing consulted most --
    # the whole document is one tool call away.
    from mcp.shared.memory import create_connected_server_and_client_session

    store = SqlConstitutionStore(url="sqlite://")
    store.create_all()
    cp = ControlPlane(store)
    cp.set_direction(**RICH, change_note="init")
    server = mcp_server.build_server(cp)

    async with create_connected_server_and_client_session(server) as client:
        result = await client.read_resource(mcp_server.RESOURCE_URI)

    payload = json.loads(result.contents[0].text)
    assert payload["mission"] == "Ship trustworthy lending"
    assert "declaration" not in payload
    assert payload["principles"] == [{"title": "Be honest"}]


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_given_a_detail_argument_when_dispatching_for_real_then_it_travels_through():
    from mcp.shared.memory import create_connected_server_and_client_session

    store = SqlConstitutionStore(url="sqlite://")
    store.create_all()
    cp = ControlPlane(store)
    cp.set_direction(**RICH, change_note="init")
    server = mcp_server.build_server(cp)

    async with create_connected_server_and_client_session(server) as client:
        compact = json.loads((await client.call_tool("get_constitution", {})).content[0].text)
        full = json.loads(
            (await client.call_tool("get_constitution", {"detail": "full"})).content[0].text
        )

    assert "declaration" not in compact
    assert full["declaration"].startswith("# Our declaration")


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_given_the_targeted_reads_when_dispatching_for_real_then_they_work():
    from mcp.shared.memory import create_connected_server_and_client_session

    store = SqlConstitutionStore(url="sqlite://")
    store.create_all()
    cp = ControlPlane(store)
    cp.set_direction(**RICH, change_note="init")
    server = mcp_server.build_server(cp)

    async with create_connected_server_and_client_session(server) as client:
        names = {t.name for t in (await client.list_tools()).tools}
        declaration = json.loads((await client.call_tool("get_declaration", {})).content[0].text)
        principle = json.loads(
            (await client.call_tool("get_principle", {"title": "Be honest"})).content[0].text
        )
        missing = await client.call_tool("get_principle", {"title": "nope"})

    assert {"get_declaration", "get_principle"} <= names
    assert declaration["declaration"].startswith("# Our declaration")
    assert principle["description"] == "Say the hard number first."
    assert missing.isError


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_given_a_compact_pull_when_an_agent_needs_more_then_it_asks_for_the_missing_piece():
    # The whole point of the targeted reads: buy the handles once, and buy
    # the paragraph only when something actually needs to read it. The
    # versions agreeing is what says the two answers describe one document.
    from mcp.shared.memory import create_connected_server_and_client_session

    store = SqlConstitutionStore(url="sqlite://")
    store.create_all()
    cp = ControlPlane(store)
    cp.set_direction(**RICH, change_note="init")
    server = mcp_server.build_server(cp)

    async with create_connected_server_and_client_session(server) as client:
        compact = json.loads((await client.call_tool("get_constitution", {})).content[0].text)
        assert "declaration" not in compact
        assert compact["principles"] == [{"title": "Be honest"}]

        title = compact["principles"][0]["title"]
        principle = json.loads(
            (await client.call_tool("get_principle", {"title": title})).content[0].text
        )
        declaration = json.loads((await client.call_tool("get_declaration", {})).content[0].text)

    assert principle["version"] == declaration["version"] == compact["version"]
    assert principle["description"] == "Say the hard number first."


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_given_the_whole_read_family_when_dispatching_for_real_then_it_works():
    from mcp.shared.memory import create_connected_server_and_client_session

    store = SqlConstitutionStore(url="sqlite://")
    store.create_all()
    cp = ControlPlane(store)
    cp.set_direction(**RICH, change_note="init", constitution="eu")
    server = mcp_server.build_server(cp)

    async def call(client, name, arguments):
        return json.loads((await client.call_tool(name, arguments)).content[0].text)

    async with create_connected_server_and_client_session(server) as client:
        mission = await call(client, "get_mission", {"constitution": "eu"})
        titles = await call(client, "get_principles", {"constitution": "eu"})
        explained = await call(client, "get_principles", {"constitution": "eu", "detail": "full"})

    assert mission == {"version": 1, "mission": "Ship trustworthy lending"}
    assert titles["principles"] == [{"title": "Be honest"}]
    assert explained["principles"][0]["description"] == "Say the hard number first."


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_given_a_connected_client_when_calling_export_versions_then_it_is_served(cp):
    """The seam the handler tests skip: the tool is advertised in the
    server's listing, the dispatch routes the call to it, and the reply
    carries the rows as JSON text. One version in, the same version out."""
    from mcp.shared.memory import create_connected_server_and_client_session

    mcp_server.handle_set_direction(
        cp, mission="M1", principles=None, change_note="init", created_by=None
    )
    async with create_connected_server_and_client_session(mcp_server.build_server(cp)) as client:
        tools = await client.list_tools()
        assert "export_versions" in [t.name for t in tools.tools]
        reply = await client.call_tool("export_versions", {})
        rows = json.loads(reply.content[0].text)
    assert [r["version"] for r in rows] == [1] and rows[0]["mission"] == "M1"


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_given_a_connected_client_when_listing_resources_then_the_constitution_is_there(cp):
    from mcp.shared.memory import create_connected_server_and_client_session

    async with create_connected_server_and_client_session(mcp_server.build_server(cp)) as client:
        listed = await client.list_resources()
    assert [str(r.uri) for r in listed.resources] == [mcp_server.RESOURCE_URI]
