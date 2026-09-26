"""Adapter calls through a running Kyno server."""

import threading
from unittest.mock import Mock

import pytest

from kyno.adapters.crewai.hooks import CrewAiKyno
from kyno.adapters.langgraph import direction_node
from kyno.sdk import connect


class FakeCtx:
    def __init__(self):
        self.messages = [{"role": "user", "content": "continue"}]


@pytest.fixture
def read_failure(live_server, monkeypatch):
    control_plane, _url, _token = live_server
    unavailable = threading.Event()
    changes_since = control_plane.changes_since

    def controlled_read(*args, **kwargs):
        if unavailable.is_set():
            raise OSError("direction read unavailable")
        return changes_since(*args, **kwargs)

    monkeypatch.setattr(control_plane, "changes_since", controlled_read)
    return unavailable


@pytest.mark.e2e
def test_given_a_live_server_when_the_adapter_refreshes_then_the_latest_direction_is_injected(
    live_server,
):
    control_plane, url, token = live_server
    control_plane.apply_direction(mission="M1", change_note="init")

    with connect(url=url, token=token) as connection:
        adapter = CrewAiKyno(connection.binder())
        context = FakeCtx()

        adapter.before_llm_call(context)
        control_plane.apply_direction(mission="M2", change_note="pivot")
        adapter.before_llm_call(context)

    direction_blocks = [message for message in context.messages if message["role"] == "system"]
    assert len(direction_blocks) == 1
    assert "constitution_key=default version=2" in direction_blocks[0]["content"]
    assert "Mission: M2" in direction_blocks[0]["content"]


@pytest.mark.e2e
def test_given_a_live_server_when_langgraph_refreshes_then_the_latest_direction_is_returned(
    live_server,
):
    pytest.importorskip("langgraph")
    from kyno.adapters.langgraph.nodes import direction_node

    control_plane, url, token = live_server
    control_plane.apply_direction(mission="M1", change_note="init")

    with connect(url=url, token=token) as connection:
        refresh = direction_node(connection.binder())
        first = refresh({})
        control_plane.apply_direction(mission="M2", change_note="pivot")
        second = refresh(first)

    assert second["kyno_version"] == 2
    assert second["kyno_mission"] == "M2"
    assert "Mission: M2" in second["kyno_direction"]


@pytest.mark.e2e
@pytest.mark.parametrize("cached", [False, True], ids=["empty", "cached"])
@pytest.mark.parametrize("wrapper", [False, True], ids=["direction-node", "pull-before"])
def test_given_read_failure_when_direction_node_or_pull_before_runs_then_fallback_clears_on_retry(
    live_server, read_failure, cached, wrapper
):
    pytest.importorskip("langgraph")
    from kyno.adapters.langgraph import direction_node, pull_before

    control_plane, url, token = live_server
    unavailable = read_failure
    control_plane.apply_direction(
        mission="Initial mission", change_note="init", constitution_key="support"
    )
    supplied = []

    def work(state):
        supplied.append(state.copy())
        return {}

    with connect(url=url, token=token) as connection:
        binder = connection.binder("support")
        refresh = pull_before(binder)(work) if wrapper else direction_node(binder)
        first = refresh({}) if cached else {}
        unavailable.set()
        fallback = refresh(first)
        control_plane.apply_direction(
            mission="Updated mission", change_note="pivot", constitution_key="support"
        )
        unavailable.clear()
        recovered = refresh(fallback)

    assert fallback["kyno_binding_status"] == ("cached" if cached else "empty")
    assert fallback["kyno_version"] == (1 if cached else 0)
    assert fallback["kyno_constitution_key"] == "support"
    if cached:
        assert first["kyno_binding_status"] == "pulled"
        assert fallback["kyno_direction"] == first["kyno_direction"]
    assert recovered["kyno_binding_status"] == "pulled"
    assert recovered["kyno_version"] == 2
    assert "Mission: Updated mission" in recovered["kyno_direction"]
    if wrapper:
        assert supplied[-2:] == [fallback, recovered]


@pytest.mark.e2e
@pytest.mark.parametrize("cached", [False, True], ids=["empty", "cached"])
def test_given_failed_reads_when_before_llm_call_runs_again_then_fallback_recovers_to_pulled(
    live_server, read_failure, cached
):
    control_plane, url, token = live_server
    control_plane.apply_direction(
        mission="Initial mission", change_note="init", constitution_key="support"
    )
    observed = []
    context = FakeCtx()

    def observe(binding):
        observed.append((binding, context.messages[0]["content"]))

    with connect(url=url, token=token) as connection:
        adapter = CrewAiKyno(connection.binder("support"), on_direction=observe)
        if cached:
            adapter.before_llm_call(context)
            control_plane.apply_direction(
                mission="Updated mission", change_note="pivot", constitution_key="support"
            )
            adapter.before_llm_call(context)
        read_failure.set()
        adapter.before_llm_call(context)
        control_plane.apply_direction(
            mission="Recovered", change_note="restore", constitution_key="support"
        )
        read_failure.clear()
        adapter.before_llm_call(context)

    fallback, recovered = [binding for binding, _block in observed[-2:]]
    assert fallback.status == ("cached" if cached else "empty")
    assert fallback.direction.version == (2 if cached else 0)
    assert recovered.status == "pulled"
    assert recovered.direction.version == (3 if cached else 2)
    assert recovered.direction.mission == "Recovered"
    if cached:
        first, second = [binding for binding, _block in observed[:2]]
        assert first.direction.version == 1
        assert second.direction.version == 2
        assert first.status == "pulled"
        assert second.status == "pulled"
    for binding, block in observed:
        assert binding.direction.constitution_key == "support"
        assert binding.direction.render() == block
    assert len([message for message in context.messages if message["role"] == "system"]) == 1


@pytest.mark.e2e
@pytest.mark.parametrize("framework", ["crewai", "langgraph"])
def test_given_omitted_adapter_key_when_pulls_cross_mcp_then_only_core_resolves_the_selection(
    live_server, monkeypatch, framework
):
    control_plane, url, token = live_server
    changes_since = Mock(wraps=control_plane.changes_since)
    monkeypatch.setattr(control_plane, "changes_since", changes_since)

    with connect(url=url, token=token) as connection:
        binder = connection.binder()
        assert binder.constitution_key is None
        if framework == "crewai":
            adapter = CrewAiKyno(binder)
            context = FakeCtx()
            adapter.before_llm_call(context)
            adapter.before_llm_call(context)
        else:
            node = direction_node(binder)
            first = node({})
            assert first["kyno_constitution_key"] == "default"
            node(first)
        assert binder.constitution_key == "default"

    assert changes_since.call_args_list[0].args == (0, None)
    assert changes_since.call_args_list[1].args == (0, "default")
