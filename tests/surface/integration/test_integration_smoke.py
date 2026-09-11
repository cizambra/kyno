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


def test_given_a_real_react_agent_when_it_runs_then_the_model_receives_direction(control_plane):
    pytest.importorskip("langgraph")
    from typing import Annotated

    from langchain_core.language_models import FakeListChatModel
    from langchain_core.messages import AnyMessage
    from langgraph.graph.message import add_messages
    from langgraph.managed import RemainingSteps
    from langgraph.prebuilt import create_react_agent

    from kyno.adapters.langgraph import KynoState, direction_node
    from kyno.sdk.binder import DirectionBinder
    from kyno.sdk.client import LocalDirectionSource

    control_plane.set_direction(mission="M1", change_note="init")
    binder = DirectionBinder(LocalDirectionSource(control_plane))

    class SupportState(KynoState):
        messages: Annotated[list[AnyMessage], add_messages]
        remaining_steps: RemainingSteps

    supplied_messages = []

    class RecordingModel(FakeListChatModel):
        def _call(self, messages, stop=None, run_manager=None, **kwargs):
            supplied_messages.extend(messages)
            return super()._call(messages, stop=stop, run_manager=run_manager, **kwargs)

    def prompt(state):
        messages = [{"role": "system", "content": state["kyno_direction"]}, *state["messages"]]
        return messages

    agent = create_react_agent(
        RecordingModel(responses=["ok"]),
        tools=[],
        pre_model_hook=direction_node(binder),
        state_schema=SupportState,
        prompt=prompt,
    )
    result = agent.invoke({"messages": [("user", "Help with a late delivery")]})

    assert result["messages"][-1].content == "ok"
    assert supplied_messages[0].content == result["kyno_direction"]
    assert "M1" in supplied_messages[0].content
