from dataclasses import replace
from unittest.mock import Mock

import pytest

pytest.importorskip("crewai")

from kyno.adapters.crewai.hooks import CrewAiKyno, TaskBlockedByKyno  # noqa: E402
from kyno.sdk.binder import DirectionBinder  # noqa: E402
from kyno.sdk.binding import DeliveryStatus  # noqa: E402
from kyno.sdk.cell import DIRECTION_MARKER  # noqa: E402
from kyno.sdk.errors import KynoUnavailableError  # noqa: E402
from kyno.sdk.gate import RealignmentGate, Verdict  # noqa: E402
from kyno.sdk.policy import PullPolicy  # noqa: E402
from kyno.sdk.trace import RunTrace  # noqa: E402
from kyno.wire.models import DetailLevel  # noqa: E402


class FakeCtx:
    """A stand-in for LLMCallHookContext: before_llm_call only touches
    messages, so this carries nothing task-shaped."""

    def __init__(self, messages=None, agent="researcher", task="Find lenders"):
        self.messages = messages if messages is not None else []
        self.agent = agent
        self.task = task


class FakeTaskOutput:
    """A stand-in for CrewAI's TaskOutput: task_callback only touches raw,
    agent (already a plain string on TaskOutput, unlike
    LLMCallHookContext.agent), and description."""

    def __init__(self, raw="", agent="researcher", description="Find lenders"):
        self.raw = raw
        self.agent = agent
        self.description = description


class StubVerdictSource:
    def __init__(self, verdict):
        self.verdict = verdict

    def assess(self, *, output, mission, principles, change_notes):
        return self.verdict


@pytest.fixture
def unit_kyno(scripted_source):
    scripted_source.set("default", 1, "M1", "Be honest")
    binder = DirectionBinder(scripted_source)
    binder.bind()
    adapter = CrewAiKyno(binder, trace=RunTrace(run_id="r1"))
    return adapter, scripted_source


def test_given_any_gate_when_before_llm_call_runs_then_it_never_blocks(unit_kyno):
    # Gating lives in task_callback alone; before_llm_call only injects direction and must
    # inject even when the gate would drift-block, or a drifted task would
    # never get a chance to run and produce the output the gate reviews.
    adapter, _cp = unit_kyno
    adapter.gate = RealignmentGate(StubVerdictSource(Verdict.DRIFTED))
    ctx = FakeCtx(messages=[{"role": "user", "content": "go"}])

    adapter.before_llm_call(ctx)

    assert ctx.messages[0]["content"].startswith(DIRECTION_MARKER)


def test_given_an_aligned_task_output_when_gating_then_it_is_not_blocked(unit_kyno):
    adapter, _cp = unit_kyno
    adapter.gate = RealignmentGate(StubVerdictSource(Verdict.ALIGNED))
    output = FakeTaskOutput(raw="on mission")

    adapter.task_callback(output)  # does not raise

    assert adapter.trace.steps[-1].verdict == "aligned" and adapter.trace.steps[-1].checked


def test_given_a_drifted_task_output_when_gating_then_it_is_blocked(unit_kyno):
    adapter, _cp = unit_kyno
    adapter.gate = RealignmentGate(StubVerdictSource(Verdict.DRIFTED))
    output = FakeTaskOutput(raw="off mission")

    with pytest.raises(TaskBlockedByKyno):
        adapter.task_callback(output)
    assert adapter.trace.steps[-1].verdict == "drifted"


def test_given_a_pause_capable_gate_when_gating_here_then_it_still_blocks(unit_kyno):
    """One gate may be shared with LangGraph; CrewAI cannot resume, so a
    pause must degrade to a block instead of passing drifted work through."""
    adapter, _cp = unit_kyno
    adapter.gate = RealignmentGate(StubVerdictSource(Verdict.DRIFTED), can_pause=True)

    with pytest.raises(TaskBlockedByKyno):
        adapter.task_callback(FakeTaskOutput(raw="off mission"))
    assert adapter.trace.steps[-1].verdict == "drifted"


def test_given_an_unjudged_task_output_when_gating_then_it_ships_marked_unchecked(unit_kyno):
    adapter, _cp = unit_kyno
    output = FakeTaskOutput(raw="whatever")

    adapter.task_callback(output)  # does not raise

    record = adapter.trace.steps[-1]
    assert record.checked is False and record.verdict == "unknown"
    assert record.constitution == "default" and record.version == 1


def test_given_the_adapter_when_inspecting_hooks_then_there_is_no_after_llm_call(unit_kyno):
    # Decided: gating is task_callback's job alone. An after_llm_call hook
    # would invite gating to creep back to per-call, so the surface simply
    # does not carry one.
    adapter, _cp = unit_kyno
    assert not hasattr(adapter, "after_llm_call")


def test_given_a_registration_when_installing_and_clearing_then_both_are_clean(unit_kyno):
    from crewai.hooks import clear_all_hooks

    adapter, _cp = unit_kyno
    try:
        adapter.register()
    finally:
        clear_all_hooks()


def test_given_a_registration_when_unregistering_then_the_hook_is_removed(unit_kyno):
    from crewai.hooks import clear_all_hooks, get_before_llm_call_hooks

    adapter, _cp = unit_kyno
    try:
        adapter.register()
        assert adapter.before_llm_call in get_before_llm_call_hooks()
        assert adapter.unregister() is True
        assert adapter.before_llm_call not in get_before_llm_call_hooks()
    finally:
        clear_all_hooks()


def test_given_the_message_list_when_injecting_then_it_is_edited_in_place(unit_kyno):
    """CrewAI's executor holds this list; rebinding it drops the injection."""
    adapter, _cp = unit_kyno
    messages = [{"role": "user", "content": "go"}]
    ctx = FakeCtx(messages=messages)

    adapter.before_llm_call(ctx)

    assert ctx.messages is messages
    assert messages[0]["content"].startswith(DIRECTION_MARKER)


def test_given_a_judged_block_when_reading_then_it_carries_the_direction_it_was_judged_against(
    unit_kyno,
):
    adapter, _cp = unit_kyno
    adapter.gate = RealignmentGate(StubVerdictSource(Verdict.DRIFTED))

    with pytest.raises(TaskBlockedByKyno) as raised:
        adapter.task_callback(FakeTaskOutput(raw="off mission"))

    assert raised.value.direction.version == 1
    assert raised.value.reason == "drifted"
    assert "constitution=default" in str(raised.value)


def test_given_a_non_system_message_with_the_marker_when_refreshing_then_it_is_not_deleted(
    unit_kyno,
):
    """The adapter replaces only the block it injected, which is a system
    message. Marker text arriving any other way (a tool result echoed into
    the transcript, or a paste from the user) is data, not something to
    delete."""
    adapter, _cp = unit_kyno
    echoed = {"role": "tool", "content": f"{DIRECTION_MARKER} constitution=x version=9]"}
    pasted = {"role": "user", "content": f"{DIRECTION_MARKER} quoted by a person"}
    ctx = FakeCtx(messages=[echoed, pasted])

    adapter.before_llm_call(ctx)

    assert echoed in ctx.messages
    assert pasted in ctx.messages
    assert ctx.messages[0]["role"] == "system"
    blocks = [m for m in ctx.messages if m["role"] == "system"]
    assert len(blocks) == 1


def test_given_messages_the_shim_does_not_understand_when_injecting_then_they_are_left_alone(
    unit_kyno,
):
    """CrewAI may hand over message objects, not dicts; never drop them."""
    adapter, _cp = unit_kyno
    other = object()
    ctx = FakeCtx(messages=[other, {"role": "user", "content": "go"}])

    adapter.before_llm_call(ctx)

    assert ctx.messages[1] is other
    assert ctx.messages[0]["content"].startswith(DIRECTION_MARKER)


def test_given_the_tap_when_a_step_runs_then_it_is_recorded_without_judgment(unit_kyno):
    adapter, _cp = unit_kyno

    adapter.step_callback(FakeTaskOutput(raw="thinking", description="Find lenders"))

    record = adapter.trace.steps[-1]
    assert record.checked is False and record.verdict == "unknown"
    assert record.version == 1


def test_given_an_output_with_nothing_to_read_when_tapping_then_it_is_still_recorded(unit_kyno):
    adapter, _cp = unit_kyno

    adapter.task_callback(FakeTaskOutput(raw=""))

    assert adapter.trace.steps[-1].output == ""


def test_given_a_trace_when_reading_it_then_the_agent_and_the_goal_are_named(unit_kyno):
    adapter, _cp = unit_kyno

    adapter.task_callback(FakeTaskOutput(raw="a list", agent="researcher", description="Find them"))

    record = adapter.trace.steps[-1]
    assert record.agent == "researcher" and record.goal == "Find them"
    assert record.output == "a list"


def test_given_no_gate_when_building_the_adapter_then_it_has_none(unit_kyno):
    """Carrying direction is the whole product; checking the work against it is
    a separate thing an operator opts into, with a judge Kyno does not ship. An
    inert gate that always answers 'unchecked' is a worse story than no gate."""
    adapter, _plane = unit_kyno
    assert adapter.gate is None


def test_given_a_gateless_adapter_when_a_step_runs_then_it_is_still_recorded(unit_kyno):
    adapter, _plane = unit_kyno

    adapter.task_callback(FakeTaskOutput(raw="anything at all"))

    assert len(adapter.trace.steps) == 1
    assert adapter.trace.steps[0].verdict == Verdict.UNKNOWN.value
    assert adapter.trace.steps[0].checked is False


@pytest.mark.parametrize("status", list(DeliveryStatus))
@pytest.mark.parametrize("context", list(DetailLevel))
def test_given_an_observer_when_direction_is_injected_then_it_receives_that_binding_after_injection(
    scripted_source, status, context
):
    scripted_source.set("support", 2, "Help customers", "Be honest")
    scripted_source.replies["support"] = replace(
        scripted_source.replies["support"],
        declaration="Explain the complete resolution.",
        delta=("Mission changed.",),
    )
    binder = DirectionBinder(scripted_source, context=context)
    if status is DeliveryStatus.CACHED:
        binder.bind("support")
    if status is not DeliveryStatus.CURRENT:
        scripted_source.failure = OSError("offline")
    scripted_source.calls.clear()
    messages = [{"role": "user", "content": "Help"}]
    ctx = FakeCtx(messages=messages)
    observed = []

    def observe(binding):
        observed.append((binding, [message.copy() for message in ctx.messages]))

    adapter = CrewAiKyno(binder, constitution="support", on_direction=observe)
    adapter.before_llm_call(ctx)

    assert len(observed) == 1
    binding, captured_messages = observed[0]
    assert binding.status is status
    assert binding.direction.constitution == "support"
    assert binding.direction.context is context
    assert binding.direction.version == (0 if status is DeliveryStatus.EMPTY else 2)
    assert captured_messages == messages
    assert messages[0]["content"] == binding.direction.render()
    assert ctx.messages is messages
    assert len(scripted_source.calls) == 1


def test_given_an_observer_returning_false_when_direction_is_injected_then_the_hook_does_not_block(
    scripted_source,
):
    scripted_source.set("default", 1, "Help")
    observer = Mock(return_value=False)
    adapter = CrewAiKyno(DirectionBinder(scripted_source), on_direction=observer)
    ctx = FakeCtx()

    assert adapter.before_llm_call(ctx) is None

    observer.assert_called_once()
    assert "Mission: Help" in ctx.messages[0]["content"]


def test_given_two_calls_when_direction_changes_then_each_observer_result_keeps_its_own_version(
    scripted_source,
):
    scripted_source.set("support", 1, "M1")
    observed = []
    adapter = CrewAiKyno(
        DirectionBinder(scripted_source), constitution="support", on_direction=observed.append
    )
    ctx = FakeCtx()
    adapter.before_llm_call(ctx)
    first_block = ctx.messages[0]["content"]
    scripted_source.set("support", 2, "M2")
    adapter.before_llm_call(ctx)

    first, second = observed
    assert first.direction.version == 1
    assert first.direction.render() == first_block
    assert second.direction.version == 2
    assert second.direction.render() == ctx.messages[0]["content"]
    assert first.status is second.status is DeliveryStatus.CURRENT
    assert len(ctx.messages) == 1


def test_given_a_broken_observer_when_direction_is_injected_then_failure_is_logged_without_escaping(
    scripted_source, caplog
):
    scripted_source.set("support", 3, "Help")
    observer = Mock(side_effect=RuntimeError("recording failed"))
    adapter = CrewAiKyno(
        DirectionBinder(scripted_source), constitution="support", on_direction=observer
    )
    ctx = FakeCtx()

    assert adapter.before_llm_call(ctx) is None

    observer.assert_called_once()
    assert "Mission: Help" in ctx.messages[0]["content"]
    assert "direction observer failed constitution=support version=3" in caplog.text
    assert any(record.exc_info for record in caplog.records)


@pytest.mark.parametrize("cached", [False, True])
def test_given_fail_closed_when_the_pull_fails_then_no_observer_runs_or_messages_change(
    scripted_source, cached
):
    scripted_source.set("default", 1, "M1")
    binder = DirectionBinder(scripted_source, policy=PullPolicy(fail_closed=True))
    if cached:
        binder.bind()
    scripted_source.failure = OSError("offline")
    observer = Mock()
    adapter = CrewAiKyno(binder, on_direction=observer)
    ctx = FakeCtx(messages=[{"role": "user", "content": "Help"}])

    with pytest.raises(KynoUnavailableError):
        adapter.before_llm_call(ctx)

    observer.assert_not_called()
    assert ctx.messages == [{"role": "user", "content": "Help"}]


def test_given_message_injection_failure_when_the_hook_runs_then_no_observer_receipt_is_emitted(
    scripted_source,
):
    class UnwritableMessages(list):
        def __setitem__(self, key, value):
            raise RuntimeError("cannot inject")

    scripted_source.set("default", 1, "M1")
    observer = Mock()
    adapter = CrewAiKyno(DirectionBinder(scripted_source), on_direction=observer)

    with pytest.raises(RuntimeError, match="cannot inject"):
        adapter.before_llm_call(FakeCtx(messages=UnwritableMessages()))

    observer.assert_not_called()
