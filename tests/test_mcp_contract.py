import asyncio
import json

import mcp.types as types
import pytest

from kyno import mcp_server
from kyno.service import ControlPlane
from kyno.store.sql import SqlConstitutionStore


@pytest.fixture
def cp():
    store = SqlConstitutionStore(url="sqlite://")
    store.create_all()
    return ControlPlane(store)


def test_given_a_set_direction_when_getting_the_constitution_then_it_round_trips(cp):
    mcp_server.handle_set_direction(
        cp, mission="M1", principles=["p1"], change_note="init", created_by="op"
    )
    d = mcp_server.handle_get_constitution(cp)
    assert d["version"] == 1 and d["mission"] == "M1"
    assert d["principles"] == [{"title": "p1"}]


def test_given_versions_when_calling_get_changes_since_then_the_changes_return(cp):
    mcp_server.handle_set_direction(
        cp, mission="M1", principles=["p1"], change_note="init", created_by=None
    )
    mcp_server.handle_set_direction(
        cp, mission="M2", principles=None, change_note="pivot", created_by=None
    )
    d = mcp_server.handle_get_changes_since(cp, 1)
    assert d["current_version"] == 2 and d["changed"] is True
    assert d["mission"] == "M2" and d["change_notes"] == ["pivot"]


def test_given_a_fresh_store_when_getting_the_constitution_then_the_empty_state_returns(cp):
    d = mcp_server.handle_get_constitution(cp)
    assert d["version"] == 0
    assert d["mission"] == ""
    assert d["principles"] == []


def test_given_a_future_version_when_calling_get_changes_since_then_valueerror_raises(cp):
    mcp_server.handle_set_direction(
        cp, mission="M1", principles=["p1"], change_note="init", created_by=None
    )
    with pytest.raises(ValueError):
        mcp_server.handle_get_changes_since(cp, 9)


def test_given_a_built_server_when_listing_registrations_then_the_expected_names_are_there(cp):
    server = mcp_server.build_server(cp)
    assert server.name == "kyno"
    assert mcp_server.RESOURCE_URI == "kyno://constitution/current"


@pytest.mark.asyncio
async def test_given_a_subscribed_session_when_the_version_bumps_then_it_is_notified(cp):
    server = mcp_server.build_server(cp)

    received = []

    class FakeSession:
        async def send_resource_updated(self, uri):
            received.append(str(uri))

    server._kyno_subscribers.add(FakeSession())
    mcp_server.handle_set_direction(
        cp, mission="M1", principles=["p1"], change_note="init", created_by=None
    )
    await asyncio.gather(*server._kyno_pending)
    assert received == [mcp_server.RESOURCE_URI]


def test_given_no_running_loop_when_notifying_then_it_is_a_noop(cp):
    # No running event loop means no async subscribers are reachable;
    # the notify hook must not raise anyway.
    server = mcp_server.build_server(cp)
    server._kyno_subscribers.add(object())
    mcp_server.handle_set_direction(
        cp, mission="M1", principles=["p1"], change_note="init", created_by=None
    )


def test_given_a_missing_known_version_when_requiring_it_then_it_raises_cleanly():
    with pytest.raises(ValueError, match="missing required argument: known_version"):
        mcp_server._require({}, "known_version")


def test_given_a_missing_change_note_when_requiring_it_then_it_raises_cleanly():
    with pytest.raises(ValueError, match="missing required argument: change_note"):
        mcp_server._require({}, "change_note")


@pytest.mark.asyncio
async def test_given_missing_required_args_when_dispatching_a_tool_call_then_the_reject_is_clean(
    cp,
):
    # Guards against a raw KeyError leaking out of dispatch instead of a clean error result.
    import mcp.types as types

    server = mcp_server.build_server(cp)
    handler = server.request_handlers[types.CallToolRequest]

    for tool_name in ("get_changes_since", "set_direction"):
        req = types.CallToolRequest(
            method="tools/call",
            params=types.CallToolRequestParams(name=tool_name, arguments={}),
        )
        result = await handler(req)
        assert result.root.isError is True


def test_given_a_no_op_change_when_calling_set_direction_then_it_maps_to_valueerror(cp):
    mcp_server.handle_set_direction(
        cp, mission="M1", principles=["p1"], change_note="init", created_by=None
    )
    with pytest.raises(ValueError):
        mcp_server.handle_set_direction(
            cp, mission="M1", principles=["p1"], change_note="noop", created_by=None
        )


def test_given_a_blank_change_note_when_calling_set_direction_then_it_maps_to_valueerror(cp):
    # _require only checks the key is present; a blank value must still be
    # rejected downstream (EmptyChangeError -> ValueError via _guard).
    with pytest.raises(ValueError):
        mcp_server.handle_set_direction(
            cp, mission="M1", principles=["p1"], change_note="   ", created_by=None
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


def _sse_json_body(response_text: str) -> dict:
    # The streamable-HTTP transport returns SSE-framed responses:
    # "event: message\ndata: {...}\n\n". Pull the JSON payload out.
    for line in response_text.splitlines():
        if line.startswith("data: "):
            return json.loads(line[len("data: ") :])
    raise AssertionError(f"no data: line in SSE body: {response_text!r}")


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
    http_app = build_http_app(cp, token=None, allow_insecure=True)
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


def test_given_the_module_when_looking_up_run_stdio_then_it_is_a_coroutine_function():
    import inspect

    from kyno.transports import run_stdio

    assert inspect.iscoroutinefunction(run_stdio)


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


def test_given_the_tool_schemas_when_inspecting_then_constitution_is_an_optional_argument():
    for tool in mcp_server._TOOLS:
        props = tool.inputSchema["properties"]
        assert props["constitution"]["type"] == "string"
        assert "constitution" not in tool.inputSchema.get("required", [])


def test_given_a_named_set_when_getting_that_name_then_it_round_trips(cp):
    mcp_server.handle_set_direction(
        cp, mission="EU1", principles=["p1"], change_note="init", created_by="op", constitution="eu"
    )
    d = mcp_server.handle_get_constitution(cp, constitution="eu")
    assert d["version"] == 1 and d["mission"] == "EU1"
    assert mcp_server.handle_get_constitution(cp)["version"] == 0


def test_given_a_name_when_calling_get_changes_since_then_it_reads_that_constitution(cp):
    mcp_server.handle_set_direction(
        cp, mission="EU1", principles=["p1"], change_note="init", created_by=None, constitution="eu"
    )
    mcp_server.handle_set_direction(
        cp, mission="EU2", principles=None, change_note="pivot", created_by=None, constitution="eu"
    )
    d = mcp_server.handle_get_changes_since(cp, 1, constitution="eu")
    assert d["current_version"] == 2 and d["mission"] == "EU2"
    assert d["change_notes"] == ["pivot"]


def test_given_an_unknown_constitution_when_reading_over_mcp_then_the_empty_state_returns(cp):
    mcp_server.handle_set_direction(
        cp, mission="M1", principles=["p1"], change_note="init", created_by=None
    )
    d = mcp_server.handle_get_constitution(cp, constitution="never-written")
    assert d["version"] == 0 and d["mission"] == "" and d["principles"] == []
    changes = mcp_server.handle_get_changes_since(cp, 4, constitution="never-written")
    assert changes["current_version"] == 0 and changes["changed"] is False


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


# --- how much of the document a read carries -------------------------------

RICH = dict(
    mission="Ship trustworthy lending",
    declaration="# Our declaration\n\nThe long form of what that means.",
    principles=[{"title": "Be honest", "description": "Say the hard number first."}],
)


def test_given_no_detail_asked_when_getting_the_constitution_then_it_is_compact(cp):
    mcp_server.handle_set_direction(cp, **RICH, change_note="init", created_by=None)

    d = mcp_server.handle_get_constitution(cp)

    assert d["mission"] == "Ship trustworthy lending"
    # Absent, not empty: "you did not ask for it" and "there is none" are
    # different answers, and only one of them is true here.
    assert "declaration" not in d
    assert d["principles"] == [{"title": "Be honest"}]


def test_given_full_detail_when_getting_the_constitution_then_the_whole_document_comes(cp):
    mcp_server.handle_set_direction(cp, **RICH, change_note="init", created_by=None)

    d = mcp_server.handle_get_constitution(cp, detail="full")

    assert d["declaration"] == "# Our declaration\n\nThe long form of what that means."
    assert d["principles"] == [{"title": "Be honest", "description": "Say the hard number first."}]


def test_given_no_detail_asked_when_calling_get_changes_since_then_metadata_still_comes(cp):
    mcp_server.handle_set_direction(cp, **RICH, change_note="init", created_by=None)
    mcp_server.handle_set_direction(
        cp, mission="M2", principles=None, change_note="pivot", created_by=None
    )

    d = mcp_server.handle_get_changes_since(cp, 1)

    assert "declaration" not in d
    assert d["principles"] == [{"title": "Be honest"}]
    assert d["changed"] is True and d["change_notes"] == ["pivot"]
    assert d["changed_mission"] is True and d["changed_principles"] is False


def test_given_full_detail_when_calling_get_changes_since_then_the_whole_document_comes(cp):
    mcp_server.handle_set_direction(cp, **RICH, change_note="init", created_by=None)
    mcp_server.handle_set_direction(
        cp, mission="M2", principles=None, change_note="pivot", created_by=None
    )

    d = mcp_server.handle_get_changes_since(cp, 1, detail="full")

    assert d["declaration"] == "# Our declaration\n\nThe long form of what that means."
    assert d["principles"] == [{"title": "Be honest", "description": "Say the hard number first."}]


@pytest.mark.parametrize("tool", ["get_constitution", "get_changes_since"])
def test_given_an_unknown_detail_when_reading_then_the_error_is_clean(cp, tool):
    with pytest.raises(ValueError, match="verbose"):
        if tool == "get_constitution":
            mcp_server.handle_get_constitution(cp, detail="verbose")
        else:
            mcp_server.handle_get_changes_since(cp, 0, detail="verbose")


def test_given_the_two_read_tools_when_inspecting_schemas_then_both_advertise_detail():
    # An agent reads the schema to learn the knob exists; a tool that hides it
    # would leave the whole document unreachable in practice.
    by_name = {t.name: t for t in mcp_server._TOOLS}
    read_tools = {n: by_name[n] for n in ("get_constitution", "get_changes_since")}
    for name, tool in read_tools.items():
        assert "detail" in tool.inputSchema["properties"], name
        assert tool.inputSchema["properties"]["detail"]["enum"] == ["compact", "full"], name
        assert "full" in tool.description, name


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


# --- targeted reads, for the piece you are missing --------------------------


def test_given_a_declaration_when_calling_get_declaration_then_it_comes_with_its_version(cp):
    mcp_server.handle_set_direction(cp, **RICH, change_note="init", created_by=None)

    d = mcp_server.handle_get_declaration(cp)

    assert d["declaration"] == "# Our declaration\n\nThe long form of what that means."
    assert d["version"] == 1


def test_given_no_declaration_when_calling_get_declaration_then_it_is_not_an_error(cp):
    # Reads never fail: "there is no declaration" is an answer, not a fault.
    mcp_server.handle_set_direction(
        cp, mission="M1", principles=None, change_note="init", created_by=None
    )
    assert mcp_server.handle_get_declaration(cp) == {"version": 1, "declaration": ""}


def test_given_an_empty_store_when_calling_get_declaration_then_version_zero_answers(cp):
    assert mcp_server.handle_get_declaration(cp) == {"version": 0, "declaration": ""}


def test_given_a_name_when_calling_get_declaration_then_it_reads_that_constitution(cp):
    mcp_server.handle_set_direction(
        cp,
        mission="EU",
        declaration="The EU long form.",
        principles=None,
        change_note="init",
        created_by=None,
        constitution="eu",
    )
    assert mcp_server.handle_get_declaration(cp, "eu")["declaration"] == "The EU long form."
    assert mcp_server.handle_get_declaration(cp)["declaration"] == ""


def test_given_a_title_when_calling_get_principle_then_one_comes_in_full_with_its_version(cp):
    mcp_server.handle_set_direction(cp, **RICH, change_note="init", created_by=None)

    d = mcp_server.handle_get_principle(cp, "Be honest")

    assert d == {
        "title": "Be honest",
        "description": "Say the hard number first.",
        "version": 1,
    }


def test_given_a_title_when_calling_get_principle_then_the_match_is_exact(cp):
    mcp_server.handle_set_direction(cp, **RICH, change_note="init", created_by=None)
    for near_miss in ("be honest", "Be honest ", "honest"):
        with pytest.raises(ValueError, match="honest"):
            mcp_server.handle_get_principle(cp, near_miss)


def test_given_a_missing_title_when_calling_get_principle_then_the_error_names_it(cp):
    # Unlike an empty store, asking about a principle that is not there is a
    # real mistake, and the message has to be enough to spot the typo.
    mcp_server.handle_set_direction(cp, **RICH, change_note="init", created_by=None)
    with pytest.raises(ValueError, match="Be hnoest"):
        mcp_server.handle_get_principle(cp, "Be hnoest")


def test_given_a_name_when_calling_get_principle_then_it_reads_that_constitution(cp):
    mcp_server.handle_set_direction(
        cp,
        mission="EU",
        principles=[{"title": "EU only", "description": "why"}],
        change_note="init",
        created_by=None,
        constitution="eu",
    )
    assert mcp_server.handle_get_principle(cp, "EU only", "eu")["description"] == "why"
    with pytest.raises(ValueError):
        mcp_server.handle_get_principle(cp, "EU only")


def test_given_two_principles_with_one_title_when_calling_get_principle_then_the_first_answers(cp):
    mcp_server.handle_set_direction(
        cp,
        mission="M",
        principles=[
            {"title": "Be honest", "description": "first"},
            {"title": "Be honest", "description": "second"},
        ],
        change_note="init",
        created_by=None,
    )
    assert mcp_server.handle_get_principle(cp, "Be honest")["description"] == "first"


def test_given_the_targeted_reads_when_inspecting_schemas_then_argument_sources_are_stated():
    tools = {t.name: t for t in mcp_server._TOOLS}
    assert "get_constitution" in tools["get_principle"].description
    assert "version" in tools["get_principle"].description
    assert "version" in tools["get_declaration"].description
    assert tools["get_principle"].inputSchema["required"] == ["title"]


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


def test_given_a_mission_when_calling_get_mission_then_the_headline_comes_with_its_version(cp):
    mcp_server.handle_set_direction(cp, **RICH, change_note="init", created_by=None)
    assert mcp_server.handle_get_mission(cp) == {
        "version": 1,
        "mission": "Ship trustworthy lending",
    }


def test_given_an_empty_store_when_calling_get_mission_then_version_zero_answers(cp):
    assert mcp_server.handle_get_mission(cp) == {"version": 0, "mission": ""}


def test_given_a_name_when_calling_get_mission_then_it_reads_that_constitution(cp):
    mcp_server.handle_set_direction(
        cp,
        mission="EU",
        principles=None,
        change_note="init",
        created_by=None,
        constitution="eu",
    )
    assert mcp_server.handle_get_mission(cp, "eu")["mission"] == "EU"
    assert mcp_server.handle_get_mission(cp)["mission"] == ""


def test_given_no_detail_asked_when_calling_get_principles_then_titles_only_come(cp):
    mcp_server.handle_set_direction(cp, **RICH, change_note="init", created_by=None)
    assert mcp_server.handle_get_principles(cp) == {
        "version": 1,
        "principles": [{"title": "Be honest"}],
    }


def test_given_explained_detail_when_calling_get_principles_then_every_description_comes(cp):
    # The slice an agent adjudicating between principles wants: all of them,
    # explained, without the mission or the declaration around them.
    mcp_server.handle_set_direction(cp, **RICH, change_note="init", created_by=None)
    assert mcp_server.handle_get_principles(cp, detail="full") == {
        "version": 1,
        "principles": [{"title": "Be honest", "description": "Say the hard number first."}],
    }


def test_given_no_principles_when_calling_get_principles_then_it_is_not_an_error(cp):
    mcp_server.handle_set_direction(
        cp, mission="M1", principles=None, change_note="init", created_by=None
    )
    assert mcp_server.handle_get_principles(cp) == {"version": 1, "principles": []}


def test_given_an_empty_store_when_calling_get_principles_then_version_zero_answers(cp):
    assert mcp_server.handle_get_principles(cp) == {"version": 0, "principles": []}


def test_given_a_detail_it_does_not_offer_when_calling_get_principles_then_it_refuses(cp):
    with pytest.raises(ValueError, match="compact"):
        mcp_server.handle_get_principles(cp, detail="compact")


def test_given_a_name_when_calling_get_principles_then_it_reads_that_constitution(cp):
    mcp_server.handle_set_direction(
        cp,
        mission="EU",
        principles=["EU only"],
        change_note="init",
        created_by=None,
        constitution="eu",
    )
    assert mcp_server.handle_get_principles(cp, "eu")["principles"] == [{"title": "EU only"}]
    assert mcp_server.handle_get_principles(cp)["principles"] == []


def test_given_the_read_family_when_answering_then_each_carries_its_source_version(cp):
    # What makes mixing reads safe: two answers with the same version
    # describe one document.
    mcp_server.handle_set_direction(cp, **RICH, change_note="init", created_by=None)
    reads = (
        mcp_server.handle_get_constitution(cp),
        mcp_server.handle_get_mission(cp),
        mcp_server.handle_get_declaration(cp),
        mcp_server.handle_get_principles(cp),
        mcp_server.handle_get_principle(cp, "Be honest"),
    )
    assert [r["version"] for r in reads] == [1, 1, 1, 1, 1]


def test_given_the_server_when_listing_tools_then_all_of_them_read_as_one_family():
    names = [t.name for t in mcp_server._TOOLS]
    assert names == [
        "get_constitution",
        "get_changes_since",
        "get_mission",
        "get_declaration",
        "get_principles",
        "get_principle",
        "export_versions",
        "set_direction",
    ]
    for tool in mcp_server._TOOLS:
        description = tool.description
        assert description.startswith("Return ") or description.startswith("Append "), tool.name
        assert description.endswith("."), tool.name
        if tool.name.startswith("get_"):
            assert "constitution" in tool.inputSchema["properties"], tool.name


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


def test_given_a_markdown_declaration_when_calling_get_declaration_then_raw_markdown_serves(cp):
    # Data is markdown. Rendering it is the public HTML page's business, and
    # an agent asking for the declaration wants the source, not a document.
    source = "# What we are for\n\n- one\n- two\n"
    mcp_server.handle_set_direction(
        cp, mission="M", declaration=source, principles=None, change_note="init", created_by=None
    )
    assert mcp_server.handle_get_declaration(cp)["declaration"] == source
    assert mcp_server.handle_get_constitution(cp, detail="full")["declaration"] == source


def test_given_versions_when_calling_export_versions_then_the_whole_history_comes_ascending(cp):
    mcp_server.handle_set_direction(
        cp, mission="M1", principles=None, change_note="init", created_by="camilo"
    )
    mcp_server.handle_set_direction(
        cp, mission="M2", principles=None, change_note="pivot", created_by=None
    )
    rows = mcp_server.handle_export_versions(cp)
    assert [r["version"] for r in rows] == [1, 2]
    assert rows[0]["mission"] == "M1" and rows[0]["change_note"] == "init"
    assert rows[0]["created_by"] == "camilo" and "created_at" in rows[0]


def test_given_bounds_when_calling_export_versions_then_they_are_inclusive(cp):
    for n in (1, 2, 3):
        mcp_server.handle_set_direction(
            cp, mission=f"M{n}", principles=None, change_note=f"n{n}", created_by=None
        )
    rows = mcp_server.handle_export_versions(cp, from_version=2, to_version=3)
    assert [r["version"] for r in rows] == [2, 3]


def test_given_an_unwritten_name_when_calling_export_versions_then_the_list_is_empty(cp):
    assert mcp_server.handle_export_versions(cp, "nope") == []


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
