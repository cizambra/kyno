"""MCP protocol behavior at the server boundary."""

import asyncio

import pytest

from kyno import mcp_server


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


@pytest.mark.asyncio
async def test_given_an_mcp_subscriber_raises_when_notifying_then_another_receives_the_update(cp):
    server = mcp_server.build_server(cp)
    received = []

    class BrokenSession:
        async def send_resource_updated(self, _uri):
            raise RuntimeError("session closed")

    class HealthySession:
        async def send_resource_updated(self, uri):
            received.append(str(uri))

    broken = BrokenSession()
    healthy = HealthySession()
    server._kyno_subscribers.update((broken, healthy))

    result = mcp_server.handle_set_direction(
        cp, mission="M1", principles=["p1"], change_note="init", created_by=None
    )
    await asyncio.gather(*server._kyno_pending)

    assert result["version"] == 1
    assert received == [mcp_server.RESOURCE_URI]
    assert server._kyno_subscribers == {healthy}


def test_given_no_running_loop_when_notifying_then_it_is_a_noop(cp):
    # No running event loop means no async subscribers are reachable;
    # the notify hook must not raise anyway.
    server = mcp_server.build_server(cp)
    server._kyno_subscribers.add(object())
    mcp_server.handle_set_direction(
        cp, mission="M1", principles=["p1"], change_note="init", created_by=None
    )


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
