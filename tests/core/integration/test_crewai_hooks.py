"""CrewAI hooks over a real control-plane source."""

import pytest

pytest.importorskip("crewai")

from kyno.adapters.crewai.hooks import CrewAiKyno  # noqa: E402
from kyno.sdk.binder import DirectionBinder  # noqa: E402
from kyno.sdk.cell import DIRECTION_MARKER  # noqa: E402
from kyno.sdk.client import LocalDirectionSource  # noqa: E402
from kyno.wire.models import DetailLevel  # noqa: E402


class FakeCtx:
    """A stand-in for LLMCallHookContext: before_llm_call only touches
    messages, so this carries nothing task-shaped."""

    def __init__(self, messages=None, agent="researcher", task="Find lenders"):
        self.messages = messages if messages is not None else []
        self.agent = agent
        self.task = task


@pytest.fixture
def crew_kyno(control_plane):
    control_plane.apply_direction(mission="M1", principles=("Be honest",), change_note="init")
    binder = DirectionBinder(LocalDirectionSource(control_plane))
    adapter = CrewAiKyno(binder)
    binder.bind()
    return adapter, control_plane


def test_given_user_message_when_before_llm_call_runs_then_direction_is_first_system_message(
    crew_kyno,
):
    adapter, _cp = crew_kyno
    ctx = FakeCtx(messages=[{"role": "user", "content": "go"}])

    adapter.before_llm_call(ctx)

    assert ctx.messages[0]["role"] == "system"
    assert ctx.messages[0]["content"].startswith(DIRECTION_MARKER)
    assert "M1" in ctx.messages[0]["content"] and "version=1" in ctx.messages[0]["content"]
    assert ctx.messages[-1] == {"role": "user", "content": "go"}


def test_given_new_direction_when_before_llm_call_runs_again_then_old_block_is_replaced(crew_kyno):
    adapter, control_plane = crew_kyno
    ctx = FakeCtx(messages=[{"role": "user", "content": "go"}])
    adapter.before_llm_call(ctx)
    control_plane.apply_direction(mission="M2", change_note="pivot")

    adapter.before_llm_call(ctx)

    blocks = [m for m in ctx.messages if m["content"].startswith(DIRECTION_MARKER)]
    assert len(blocks) == 1
    assert "M2" in blocks[0]["content"] and "version=2" in blocks[0]["content"]


def test_given_european_binder_when_before_llm_call_runs_then_european_direction_is_injected(
    control_plane,
):
    binder = DirectionBinder(LocalDirectionSource(control_plane), "eu")
    control_plane.apply_direction(
        mission="European mission", change_note="Initial", constitution_key="eu"
    )
    context = FakeCtx()
    CrewAiKyno(binder).before_llm_call(context)
    assert "constitution_key=eu version=1" in context.messages[0]["content"]
    assert "European mission" in context.messages[0]["content"]


def test_given_full_detail_when_before_llm_call_runs_then_declaration_and_descriptions_are_added(
    control_plane,
):
    control_plane.apply_direction(
        mission="M1",
        declaration="The long form.",
        principles=({"title": "Be honest", "description": "Say the hard number first."},),
        change_note="init",
    )
    binder = DirectionBinder(LocalDirectionSource(control_plane), detail=DetailLevel.FULL)
    adapter = CrewAiKyno(binder)
    ctx = FakeCtx(messages=[{"role": "user", "content": "go"}])

    adapter.before_llm_call(ctx)

    injected = ctx.messages[0]["content"]
    assert "The long form." in injected
    assert "Say the hard number first." in injected


def test_given_default_detail_when_before_llm_call_runs_then_only_mission_and_titles_are_added(
    control_plane,
):
    control_plane.apply_direction(
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
