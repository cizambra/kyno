"""CrewAI hooks over a real control-plane source."""

import pytest

pytest.importorskip("crewai")

from kyno.adapters.crewai.hooks import CrewAiKyno  # noqa: E402
from kyno.sdk.binder import DirectionBinder  # noqa: E402
from kyno.sdk.cell import DIRECTION_MARKER, FULL  # noqa: E402
from kyno.sdk.client import LocalDirectionSource  # noqa: E402
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
    binder.bind()
    return adapter, control_plane


def test_given_a_model_call_when_the_hook_runs_then_the_direction_is_injected_first(crew_kyno):
    adapter, _cp = crew_kyno
    ctx = FakeCtx(messages=[{"role": "user", "content": "go"}])

    adapter.before_llm_call(ctx)

    assert ctx.messages[0]["role"] == "system"
    assert ctx.messages[0]["content"].startswith(DIRECTION_MARKER)
    assert "M1" in ctx.messages[0]["content"] and "version=1" in ctx.messages[0]["content"]
    assert ctx.messages[-1] == {"role": "user", "content": "go"}


def test_given_a_second_call_when_injecting_then_the_block_is_replaced_not_stacked(crew_kyno):
    adapter, control_plane = crew_kyno
    ctx = FakeCtx(messages=[{"role": "user", "content": "go"}])
    adapter.before_llm_call(ctx)
    control_plane.set_direction(mission="M2", change_note="pivot")

    adapter.before_llm_call(ctx)

    blocks = [m for m in ctx.messages if m["content"].startswith(DIRECTION_MARKER)]
    assert len(blocks) == 1
    assert "M2" in blocks[0]["content"] and "version=2" in blocks[0]["content"]


def test_given_the_adapter_when_asking_then_it_reports_which_constitution_it_serves(control_plane):
    binder = DirectionBinder(LocalDirectionSource(control_plane))
    assert CrewAiKyno(binder, constitution="eu").constitution == "eu"


def test_given_a_shared_cell_when_the_gate_judges_then_it_uses_the_cell_not_its_own_pull(crew_kyno):
    """Freshness is the binder's and subscriber's job; a pull here would double it."""
    adapter, control_plane = crew_kyno
    adapter.before_llm_call(FakeCtx(messages=[]))
    control_plane.set_direction(mission="M2", change_note="pivot")

    adapter.task_callback(FakeTaskOutput(raw="done"))

    assert adapter.trace.steps[-1].version == 1


def test_given_no_trace_when_the_tap_runs_then_it_is_a_no_op(control_plane):
    control_plane.set_direction(mission="M1", change_note="init")
    adapter = CrewAiKyno(DirectionBinder(LocalDirectionSource(control_plane)))

    adapter.step_callback(FakeTaskOutput(raw="thinking"))  # does not raise

    assert adapter.trace is None


def test_given_no_bound_direction_when_gating_a_task_then_version_zero_is_recorded(control_plane):
    """A crew can finish a task before the first pull ever lands."""
    adapter = CrewAiKyno(
        DirectionBinder(LocalDirectionSource(control_plane)), trace=RunTrace(run_id="r1")
    )

    adapter.task_callback(FakeTaskOutput(raw="done"))

    assert adapter.trace.steps[-1].version == 0


def test_given_a_full_binder_when_injecting_then_the_message_carries_the_full_document(
    control_plane,
):
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


def test_given_no_context_asked_when_injecting_then_the_message_stays_compact(control_plane):
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
