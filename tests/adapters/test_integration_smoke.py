import os

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("KYNO_INTEGRATION") != "1",
        reason="set KYNO_INTEGRATION=1 to run the orchestrator smokes",
    ),
]


def test_given_the_real_crewai_api_when_registering_hooks_then_they_are_registered(control_plane):
    crewai_hooks = pytest.importorskip("crewai.hooks")
    from kyno.adapters.crewai.hooks import CrewAiKyno
    from kyno.sdk.binder import DirectionBinder
    from kyno.sdk.client import LocalDirectionSource

    control_plane.set_direction(mission="M1", change_note="init")
    adapter = CrewAiKyno(DirectionBinder(LocalDirectionSource(control_plane)))
    try:
        adapter.register()
        assert adapter.before_llm_call in crewai_hooks.get_before_llm_call_hooks()
    finally:
        crewai_hooks.clear_all_hooks()


def test_given_a_real_react_agent_when_wiring_the_hooks_then_it_accepts_them(control_plane):
    pytest.importorskip("langgraph")
    from langchain_core.language_models import FakeListChatModel
    from langgraph.prebuilt import create_react_agent

    from kyno.adapters.langgraph.nodes import direction_node, gate_node
    from kyno.sdk.binder import DirectionBinder
    from kyno.sdk.client import LocalDirectionSource
    from kyno.sdk.gate import RealignmentGate

    control_plane.set_direction(mission="M1", change_note="init")
    binder = DirectionBinder(LocalDirectionSource(control_plane))

    # No network: the prebuilt agent wants a real chat model, and langchain
    # ships a scripted one.
    agent = create_react_agent(
        FakeListChatModel(responses=["ok"]),
        tools=[],
        pre_model_hook=direction_node(binder),
        post_model_hook=gate_node(RealignmentGate(can_pause=True)),
    )
    assert agent is not None
