"""MCP protocol behavior at the server boundary."""

import asyncio

import pytest

from kyno.mcp import handlers as mcp_handlers, server as mcp_server
from kyno.wire import RESOURCE_URI


@pytest.mark.parametrize("version", [-1, True, 1.0, 1.5, "1"])
@pytest.mark.parametrize("operation", ["get_changes_since", "apply_direction"])
def test_given_invalid_version_when_call_tool_is_called_then_request_is_rejected(
    mcp_runner, operation, version
):
    runner, control_plane = mcp_runner
    control_plane.apply_direction(mission="Original", change_note="init")
    arguments = (
        {"last_seen_version": version}
        if operation == "get_changes_since"
        else {"expected_version": version, "mission": "Updated", "change_note": "update"}
    )

    result = runner.call(lambda session: session.call_tool(operation, arguments))

    assert result.isError
    assert control_plane.current().version == 1
    assert control_plane.current().mission == "Original"


@pytest.mark.asyncio
async def test_given_a_subscribed_session_when_the_version_bumps_then_it_is_notified(cp):
    server = mcp_server.build_server(cp)

    received = []

    class FakeSession:
        async def send_resource_updated(self, uri):
            received.append(str(uri))

    server._kyno_subscribers.add(FakeSession())
    mcp_handlers.handle_apply_direction(
        cp, mission="M1", principles=["p1"], change_note="init", created_by=None
    )
    await asyncio.gather(*server._kyno_pending)
    assert received == [RESOURCE_URI]


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

    result = mcp_handlers.handle_apply_direction(
        cp, mission="M1", principles=["p1"], change_note="init", created_by=None
    )
    await asyncio.gather(*server._kyno_pending)

    assert result["version"] == 1
    assert received == [RESOURCE_URI]
    assert server._kyno_subscribers == {healthy}


def test_given_no_running_loop_when_notifying_then_it_is_a_noop(cp):
    # No running event loop means no async subscribers are reachable;
    # the notify hook must not raise anyway.
    server = mcp_server.build_server(cp)
    server._kyno_subscribers.add(object())
    mcp_handlers.handle_apply_direction(
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

    for tool_name in ("get_changes_since", "apply_direction"):
        req = types.CallToolRequest(
            method="tools/call",
            params=types.CallToolRequestParams(name=tool_name, arguments={}),
        )
        result = await handler(req)
        assert result.root.isError is True
