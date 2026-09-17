"""CrewAI's registered before-call hook exposes the direction injected into its real context."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

pytest.importorskip("crewai")

from crewai.crews.crew_output import CrewOutput  # noqa: E402
from crewai.hooks import LLMCallHookContext, get_before_llm_call_hooks  # noqa: E402

from kyno.adapters.crewai import CrewAiKyno  # noqa: E402
from kyno.sdk import (  # noqa: E402
    DeliveryStatus,
    DirectionBinder,
    DirectionResponse,
    RecordingReceipt,
)
from kyno.wire.models import ChangesSince  # noqa: E402


@pytest.mark.parametrize("observer_fails", [False, True])
def test_given_registered_hook_when_before_llm_call_runs_then_observer_sees_injected_messages(
    observer_fails,
):
    source = SimpleNamespace(
        changes_since=Mock(
            return_value=DirectionResponse(
                ChangesSince(
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


def test_given_saved_direction_when_before_llm_call_refreshes_then_app_can_assess_prior_version():
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
    source = SimpleNamespace(
        changes_since=Mock(side_effect=[DirectionResponse(first), DirectionResponse(second)])
    )
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
    assert get_before_llm_call_hooks() == previous_hooks


@pytest.mark.parametrize("recording_status", ["recorded", "disabled", "failed", None])
@pytest.mark.parametrize("delivery_status", list(DeliveryStatus))
def test_given_receipt_when_before_llm_call_runs_then_observer_receives_injected_direction_receipt(
    recording_status, delivery_status
):
    receipt = (
        RecordingReceipt(
            status=recording_status,
            record_id="delivery-1" if recording_status == "recorded" else None,
        )
        if recording_status is not None
        else None
    )
    source = SimpleNamespace(
        changes_since=Mock(
            return_value=DirectionResponse(
                changes=ChangesSince(1, True, "Help customers", (), True, False, ("init",)),
                recording=receipt,
            )
        )
    )
    binder = DirectionBinder(source)
    if delivery_status is DeliveryStatus.CACHED:
        binder.bind()
    if delivery_status is not DeliveryStatus.CURRENT:
        source.changes_since.side_effect = OSError("offline")
    source.changes_since.reset_mock()
    executor = SimpleNamespace(
        messages=[], llm=None, iterations=0, agent=None, task=None, crew=None
    )
    context = LLMCallHookContext(executor=executor)
    observed = []

    def observe(binding):
        assert context.messages[0]["content"] == binding.direction.render()
        observed.append(binding)

    adapter = CrewAiKyno(binder, on_direction=observe)
    assert adapter.before_llm_call(context) is None

    assert len(observed) == 1
    assert observed[0].status is delivery_status
    assert observed[0].recording is (None if delivery_status is DeliveryStatus.EMPTY else receipt)
    assert source.changes_since.call_count == 1


def test_given_same_version_when_before_llm_call_runs_twice_then_observed_receipts_are_distinct():
    changes = ChangesSince(1, True, "Help customers", (), True, False, ("init",))
    source = SimpleNamespace(
        changes_since=Mock(
            side_effect=[
                DirectionResponse(changes, RecordingReceipt("recorded", "delivery-1")),
                DirectionResponse(changes, RecordingReceipt("recorded", "delivery-2")),
            ]
        )
    )
    executor = SimpleNamespace(
        messages=[], llm=None, iterations=0, agent=None, task=None, crew=None
    )
    context = LLMCallHookContext(executor=executor)
    observed = []
    adapter = CrewAiKyno(DirectionBinder(source), on_direction=observed.append)

    adapter.before_llm_call(context)
    first_messages = [message.copy() for message in context.messages]
    adapter.before_llm_call(context)

    assert observed[0].recording.record_id == "delivery-1"
    assert observed[1].recording.record_id == "delivery-2"
    assert observed[0].direction.version == observed[1].direction.version == 1
    assert observed[0].direction.render() == first_messages[0]["content"]
    assert observed[1].direction.render() == context.messages[0]["content"]
