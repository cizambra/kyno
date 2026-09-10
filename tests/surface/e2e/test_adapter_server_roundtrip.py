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

    with connect(url=url, token=token) as connection:
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

    with connect(url=url, token=token) as connection:
        refresh = direction_node(connection.binder())
        first = refresh({})
        control_plane.set_direction(mission="M2", change_note="pivot")
        second = refresh(first)

    assert second["kyno_version"] == 2
    assert second["kyno_mission"] == "M2"
    assert "Mission: M2" in second["kyno_direction"]


@pytest.mark.e2e
@pytest.mark.parametrize("cached", [False, True], ids=["empty", "cached"])
@pytest.mark.parametrize("wrapper", [False, True], ids=["direction-node", "pull-before"])
def test_given_server_read_failure_when_langgraph_pulls_over_http_then_fallback_clears_on_recovery(
    live_server, monkeypatch, cached, wrapper
):
    pytest.importorskip("langgraph")
    from kyno.adapters.langgraph import direction_node, pull_before

    control_plane, url, token = live_server
    unavailable = threading.Event()
    changes_since = control_plane.changes_since

    def controlled_read(*args, **kwargs):
        if unavailable.is_set():
            raise OSError("direction read unavailable")
        return changes_since(*args, **kwargs)

    monkeypatch.setattr(control_plane, "changes_since", controlled_read)
    control_plane.set_direction(mission="M1", change_note="init", constitution="support")
    supplied = []

    def work(state):
        supplied.append(state.copy())
        return {}

    with connect(url=url, token=token) as connection:
        binder = connection.binder()
        refresh = (
            pull_before(binder, "support")(work) if wrapper else direction_node(binder, "support")
        )
        first = refresh({}) if cached else {}
        unavailable.set()
        fallback = refresh(first)
        control_plane.set_direction(mission="M2", change_note="pivot", constitution="support")
        unavailable.clear()
        recovered = refresh(fallback)

    assert fallback["kyno_delivery_status"] == ("cached" if cached else "empty")
    assert fallback["kyno_version"] == (1 if cached else 0)
    assert fallback["kyno_constitution"] == "support"
    if cached:
        assert first["kyno_delivery_status"] == "current"
        assert fallback["kyno_direction"] == first["kyno_direction"]
    assert recovered["kyno_delivery_status"] == "current"
    assert recovered["kyno_version"] == 2
    assert "Mission: M2" in recovered["kyno_direction"]
    if wrapper:
        assert supplied[-2:] == [fallback, recovered]
