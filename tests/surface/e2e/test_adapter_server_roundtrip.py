"""Adapter calls through a running Kyno server."""

import threading

import pytest
import uvicorn

from kyno.adapters.crewai.hooks import CrewAiKyno
from kyno.sdk import connect
from kyno.service import ControlPlane
from kyno.transports import build_http_app
from tests.mcp_requests import mint, token_store
from tests.servers import free_port, wait_until


class FakeCtx:
    def __init__(self):
        self.messages = [{"role": "user", "content": "continue"}]


@pytest.fixture
def live_server():
    store = token_store()
    control_plane = ControlPlane(store)
    token = mint(store, scope="read")
    app = build_http_app(control_plane, token_store=store)
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        wait_until(lambda: server.started, "uvicorn did not come up")
        yield control_plane, f"http://127.0.0.1:{port}/mcp", token
    finally:
        server.should_exit = True
        thread.join(timeout=5)


@pytest.mark.e2e
def test_given_a_live_server_when_the_adapter_refreshes_then_the_latest_direction_is_injected(
    live_server,
):
    control_plane, url, token = live_server
    control_plane.set_direction(mission="M1", change_note="init")

    with connect(url, token) as connection:
        adapter = CrewAiKyno(connection.binder())
        context = FakeCtx()

        adapter.before_llm_call(context)
        control_plane.set_direction(mission="M2", change_note="pivot")
        adapter.before_llm_call(context)

    direction_blocks = [message for message in context.messages if message["role"] == "system"]
    assert len(direction_blocks) == 1
    assert "constitution=default version=2" in direction_blocks[0]["content"]
    assert "Mission: M2" in direction_blocks[0]["content"]


@pytest.mark.e2e
def test_given_a_live_server_when_langgraph_refreshes_then_the_latest_direction_is_returned(
    live_server,
):
    pytest.importorskip("langgraph")
    from kyno.adapters.langgraph.nodes import direction_node

    control_plane, url, token = live_server
    control_plane.set_direction(mission="M1", change_note="init")

    with connect(url, token) as connection:
        refresh = direction_node(connection.binder())
        first = refresh({})
        control_plane.set_direction(mission="M2", change_note="pivot")
        second = refresh(first)

    assert second["kyno_version"] == 2
    assert second["kyno_mission"] == "M2"
    assert "Mission: M2" in second["kyno_direction"]
