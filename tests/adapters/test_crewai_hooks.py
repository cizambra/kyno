import pytest

pytest.importorskip("crewai")

from kyno.adapters.crewai.hooks import CrewAiKyno, TaskBlockedByKyno  # noqa: E402
from kyno.sdk.binder import DirectionBinder  # noqa: E402
from kyno.sdk.cell import DIRECTION_MARKER, FULL  # noqa: E402
from kyno.sdk.client import LocalDirectionSource  # noqa: E402
from kyno.sdk.gate import RealignmentGate, Verdict  # noqa: E402
from kyno.sdk.trace import RunTrace  # noqa: E402


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
def crew_kyno(control_plane):
    control_plane.set_direction(mission="M1", principles=("Be honest",), change_note="init")
    binder = DirectionBinder(LocalDirectionSource(control_plane))
    adapter = CrewAiKyno(binder, trace=RunTrace(run_id="r1"))
    adapter.bound_direction()  # warm the cell, as the first before_llm_call would
    return adapter, control_plane


def test_the_direction_is_injected_before_the_model_call(crew_kyno):
    adapter, _cp = crew_kyno
    ctx = FakeCtx(messages=[{"role": "user", "content": "go"}])

    adapter.before_llm_call(ctx)

    assert ctx.messages[0]["role"] == "system"
    assert ctx.messages[0]["content"].startswith(DIRECTION_MARKER)
    assert "M1" in ctx.messages[0]["content"] and "version=1" in ctx.messages[0]["content"]
    assert ctx.messages[-1] == {"role": "user", "content": "go"}


def test_a_second_call_replaces_the_block_instead_of_stacking(crew_kyno):
    adapter, control_plane = crew_kyno
    ctx = FakeCtx(messages=[{"role": "user", "content": "go"}])
    adapter.before_llm_call(ctx)
    control_plane.set_direction(mission="M2", change_note="pivot")

    adapter.before_llm_call(ctx)

    blocks = [m for m in ctx.messages if m["content"].startswith(DIRECTION_MARKER)]
    assert len(blocks) == 1
    assert "M2" in blocks[0]["content"] and "version=2" in blocks[0]["content"]


def test_before_llm_call_never_blocks_regardless_of_the_gate(crew_kyno):
    # Gating lives in task_callback alone; before_llm_call only injects direction and must
    # inject even when the gate would drift-block, or a drifted task would
    # never get a chance to run and produce the output the gate reviews.
    adapter, _cp = crew_kyno
    adapter.gate = RealignmentGate(StubVerdictSource(Verdict.DRIFTED))
    ctx = FakeCtx(messages=[{"role": "user", "content": "go"}])

    adapter.before_llm_call(ctx)

    assert ctx.messages[0]["content"].startswith(DIRECTION_MARKER)


def test_the_adapter_reports_which_constitution_it_serves(control_plane):
    binder = DirectionBinder(LocalDirectionSource(control_plane))
    assert CrewAiKyno(binder, constitution="eu").constitution == "eu"


def test_an_aligned_task_output_is_not_blocked(crew_kyno):
    adapter, _cp = crew_kyno
    adapter.gate = RealignmentGate(StubVerdictSource(Verdict.ALIGNED))
    output = FakeTaskOutput(raw="on mission")

    adapter.task_callback(output)  # does not raise

    assert adapter.trace.steps[-1].verdict == "aligned" and adapter.trace.steps[-1].checked


def test_a_drifted_task_output_is_blocked(crew_kyno):
    adapter, _cp = crew_kyno
    adapter.gate = RealignmentGate(StubVerdictSource(Verdict.DRIFTED))
    output = FakeTaskOutput(raw="off mission")

    with pytest.raises(TaskBlockedByKyno):
        adapter.task_callback(output)
    assert adapter.trace.steps[-1].verdict == "drifted"


def test_a_pause_capable_gate_still_blocks_here(crew_kyno):
    """One gate may be shared with LangGraph; CrewAI cannot resume, so a
    pause must degrade to a block instead of passing drifted work through."""
    adapter, _cp = crew_kyno
    adapter.gate = RealignmentGate(StubVerdictSource(Verdict.DRIFTED), can_pause=True)

    with pytest.raises(TaskBlockedByKyno):
        adapter.task_callback(FakeTaskOutput(raw="off mission"))
    assert adapter.trace.steps[-1].verdict == "drifted"


def test_an_unjudged_task_output_ships_marked_unchecked(crew_kyno):
    adapter, _cp = crew_kyno
    output = FakeTaskOutput(raw="whatever")

    adapter.task_callback(output)  # does not raise

    record = adapter.trace.steps[-1]
    assert record.checked is False and record.verdict == "unknown"
    assert record.constitution == "default" and record.version == 1


def test_the_adapter_has_no_after_llm_call_hook(crew_kyno):
    # Decided: gating is task_callback's job alone. An after_llm_call hook
    # would invite gating to creep back to per-call, so the surface simply
    # does not carry one.
    adapter, _cp = crew_kyno
    assert not hasattr(adapter, "after_llm_call")


def test_registration_installs_and_clears_cleanly(crew_kyno):
    from crewai.hooks import clear_all_hooks

    adapter, _cp = crew_kyno
    try:
        adapter.register()
    finally:
        clear_all_hooks()


def test_registration_lands_the_hook_and_unregistration_removes_it(crew_kyno):
    from crewai.hooks import clear_all_hooks, get_before_llm_call_hooks

    adapter, _cp = crew_kyno
    try:
        adapter.register()
        assert adapter.before_llm_call in get_before_llm_call_hooks()
        assert adapter.unregister() is True
        assert adapter.before_llm_call not in get_before_llm_call_hooks()
    finally:
        clear_all_hooks()


def test_the_message_list_is_edited_in_place(crew_kyno):
    """CrewAI's executor holds this list; rebinding it drops the injection."""
    adapter, _cp = crew_kyno
    messages = [{"role": "user", "content": "go"}]
    ctx = FakeCtx(messages=messages)

    adapter.before_llm_call(ctx)

    assert ctx.messages is messages
    assert messages[0]["content"].startswith(DIRECTION_MARKER)


def test_the_block_carries_the_direction_it_was_judged_against(crew_kyno):
    adapter, _cp = crew_kyno
    adapter.gate = RealignmentGate(StubVerdictSource(Verdict.DRIFTED))

    with pytest.raises(TaskBlockedByKyno) as raised:
        adapter.task_callback(FakeTaskOutput(raw="off mission"))

    assert raised.value.direction.version == 1
    assert raised.value.reason == "drifted"
    assert "constitution=default" in str(raised.value)


def test_the_gate_judges_against_the_shared_cell_not_its_own_pull(crew_kyno):
    """Freshness is the binder's and subscriber's job; a pull here would double it."""
    adapter, control_plane = crew_kyno
    adapter.before_llm_call(FakeCtx(messages=[]))
    control_plane.set_direction(mission="M2", change_note="pivot")

    adapter.task_callback(FakeTaskOutput(raw="done"))

    assert adapter.trace.steps[-1].version == 1


def test_a_non_system_message_carrying_the_marker_is_not_deleted(crew_kyno):
    """Only the block this adapter injected -- a system message -- is its to
    replace. Marker text arriving any other way (a tool result echoed into
    the transcript, a user paste) is data, not a deletion instruction."""
    adapter, _cp = crew_kyno
    echoed = {"role": "tool", "content": f"{DIRECTION_MARKER} constitution=x version=9]"}
    pasted = {"role": "user", "content": f"{DIRECTION_MARKER} quoted by a person"}
    ctx = FakeCtx(messages=[echoed, pasted])

    adapter.before_llm_call(ctx)

    assert echoed in ctx.messages
    assert pasted in ctx.messages
    assert ctx.messages[0]["role"] == "system"
    blocks = [m for m in ctx.messages if m["role"] == "system"]
    assert len(blocks) == 1


def test_messages_the_shim_does_not_understand_are_left_alone(crew_kyno):
    """CrewAI may hand over message objects, not dicts; never drop them."""
    adapter, _cp = crew_kyno
    other = object()
    ctx = FakeCtx(messages=[other, {"role": "user", "content": "go"}])

    adapter.before_llm_call(ctx)

    assert ctx.messages[1] is other
    assert ctx.messages[0]["content"].startswith(DIRECTION_MARKER)


def test_the_tap_records_a_step_without_judging_it(crew_kyno):
    adapter, _cp = crew_kyno

    adapter.step_callback(FakeTaskOutput(raw="thinking", description="Find lenders"))

    record = adapter.trace.steps[-1]
    assert record.checked is False and record.verdict == "unknown"
    assert record.version == 1


def test_the_tap_is_a_no_op_without_a_trace(control_plane):
    control_plane.set_direction(mission="M1", change_note="init")
    adapter = CrewAiKyno(DirectionBinder(LocalDirectionSource(control_plane)))

    adapter.step_callback(FakeTaskOutput(raw="thinking"))  # does not raise

    assert adapter.trace is None


def test_an_output_with_nothing_to_read_is_still_recorded(crew_kyno):
    adapter, _cp = crew_kyno

    adapter.task_callback(FakeTaskOutput(raw=""))

    assert adapter.trace.steps[-1].output == ""


def test_a_task_gated_before_any_direction_was_bound_records_version_zero(control_plane):
    """A crew can finish a task before the first pull ever lands."""
    adapter = CrewAiKyno(
        DirectionBinder(LocalDirectionSource(control_plane)), trace=RunTrace(run_id="r1")
    )

    adapter.task_callback(FakeTaskOutput(raw="done"))

    assert adapter.trace.steps[-1].version == 0


def test_the_trace_names_the_agent_and_the_goal(crew_kyno):
    adapter, _cp = crew_kyno

    adapter.task_callback(FakeTaskOutput(raw="a list", agent="researcher", description="Find them"))

    record = adapter.trace.steps[-1]
    assert record.agent == "researcher" and record.goal == "Find them"
    assert record.output == "a list"


def test_the_injected_message_carries_the_full_document_when_the_binder_says_so(control_plane):
    control_plane.set_direction(
        mission="M1",
        declaration="The long form.",
        principles=({"title": "Be honest", "description": "Say the hard number first."},),
        change_note="init",
    )
    binder = DirectionBinder(LocalDirectionSource(control_plane), context=FULL)
    adapter = CrewAiKyno(binder)
    ctx = FakeCtx(messages=[{"role": "user", "content": "go"}])

    adapter.before_llm_call(ctx)

    injected = ctx.messages[0]["content"]
    assert "The long form." in injected
    assert "Say the hard number first." in injected


def test_the_injected_message_stays_compact_by_default(control_plane):
    control_plane.set_direction(
        mission="M1",
        declaration="The long form.",
        principles=({"title": "Be honest", "description": "Say the hard number first."},),
        change_note="init",
    )
    adapter = CrewAiKyno(DirectionBinder(LocalDirectionSource(control_plane)))
    ctx = FakeCtx()

    adapter.before_llm_call(ctx)

    injected = ctx.messages[0]["content"]
    assert "Be honest" in injected
    assert "The long form." not in injected
    assert "Say the hard number first." not in injected


def test_an_adapter_with_no_gate_has_none(crew_kyno):
    """Carrying direction is the whole product; checking the work against it is
    a separate thing an operator opts into, with a judge Kyno does not ship. An
    inert gate that always answers 'unchecked' is a worse story than no gate."""
    adapter, _plane = crew_kyno
    assert adapter.gate is None


def test_a_gateless_adapter_still_records_the_step(crew_kyno):
    adapter, _plane = crew_kyno

    adapter.task_callback(FakeTaskOutput(raw="anything at all"))

    assert len(adapter.trace.steps) == 1
    assert adapter.trace.steps[0].verdict == Verdict.UNKNOWN.value
    assert adapter.trace.steps[0].checked is False
