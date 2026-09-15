"""CrewAI's registered before-call hook exposes the direction injected into its real context."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

pytest.importorskip("crewai")

from crewai.crews.crew_output import CrewOutput  # noqa: E402
from crewai.hooks import LLMCallHookContext, get_before_llm_call_hooks  # noqa: E402

from kyno.adapters.crewai import CrewAiKyno  # noqa: E402
from kyno.sdk import DirectionBinder  # noqa: E402
from kyno.wire.models import ChangesSince  # noqa: E402


@pytest.mark.parametrize("observer_fails", [False, True])
def test_given_a_registered_hook_when_crewai_calls_it_then_the_observer_sees_injected_messages(
    observer_fails,
):
    source = SimpleNamespace(
        changes_since=Mock(
            return_value=ChangesSince(
                current_version=2,
                changed=True,
                mission="Help customers",
                principles=(),
                changed_mission=True,
                changed_principles=False,
                change_notes=("Support first",),
            )
        )
    )
    messages = [{"role": "user", "content": "Help"}]
    executor = SimpleNamespace(
        messages=messages, llm=None, iterations=0, agent=None, task=None, crew=None
    )
    context = LLMCallHookContext(executor=executor)
    observed = []

    def observe(binding):
        observed.append((binding, [message.copy() for message in context.messages]))
        if observer_fails:
            raise RuntimeError("recording unavailable")

    adapter = CrewAiKyno(DirectionBinder(source), on_direction=observe)
    previous_hooks = list(get_before_llm_call_hooks())
    adapter.register()
    try:
        hook = next(hook for hook in get_before_llm_call_hooks() if hook == adapter.before_llm_call)
        assert hook(context) is None
    finally:
        adapter.unregister()

    assert get_before_llm_call_hooks() == previous_hooks
    assert context.messages is executor.messages is messages
    assert len(observed) == 1
    binding, captured = observed[0]
    assert captured == messages
    assert binding.direction.render() == messages[0]["content"]
    assert binding.status == "current"
    assert source.changes_since.call_count == 1


def test_given_a_snapshot_when_direction_changes_then_assessment_uses_the_selected_version():
    first = ChangesSince(
        current_version=1,
        changed=True,
        mission="Help customers",
        principles=(),
        changed_mission=True,
        changed_principles=False,
        change_notes=("init",),
    )
    second = replace(first, current_version=2, mission="Help partners", change_notes=("pivot",))
    source = SimpleNamespace(changes_since=Mock(side_effect=[first, second]))
    binder = DirectionBinder(source)
    assessment_direction = binder.bind()
    executor = SimpleNamespace(
        messages=[{"role": "user", "content": "Help"}],
        llm=None,
        iterations=0,
        agent=None,
        task=None,
        crew=None,
    )
    context = LLMCallHookContext(executor=executor)
    observed = []
    assessed = []

    def assess_output(*, output, direction):
        assessed.append((output, direction))
        return output == direction.mission

    adapter = CrewAiKyno(binder, on_direction=observed.append)
    previous_hooks = list(get_before_llm_call_hooks())
    adapter.register()
    try:
        adapter.before_llm_call(context)
        result = CrewOutput(raw="Help customers")
    finally:
        adapter.unregister()

    assessment = assess_output(output=result.raw, direction=assessment_direction)

    assert assessment is True
    assert assessed == [(result.raw, assessment_direction)]
    assert assessment_direction.version == 1
    assert assessment_direction.mission == "Help customers"
    assert observed[0].direction.version == 2
    assert observed[0].direction.render() == context.messages[0]["content"]
    assert binder.cell.get("default").version == 2
    assert get_before_llm_call_hooks() == previous_hooks
