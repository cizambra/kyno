import pytest

pytest.importorskip("langgraph")

from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402
from langgraph.graph import END, START, StateGraph  # noqa: E402
from langgraph.types import Command  # noqa: E402

from kyno.adapters.langgraph.nodes import (  # noqa: E402
    KynoState,
    direction_from_state,
    direction_node,
    direction_update,
    gate_node,
    pull_before,
)
from kyno.sdk.binder import DirectionBinder  # noqa: E402
from kyno.sdk.cell import (  # noqa: E402
    COMPACT,
    DIRECTION_MARKER,
    FULL,
    Direction,
)
from kyno.sdk.client import LocalDirectionSource  # noqa: E402
from kyno.sdk.gate import RealignmentGate, Verdict  # noqa: E402
from kyno.sdk.trace import RunTrace  # noqa: E402


class GraphState(KynoState, total=False):
    output: str
    draft: str


class StubVerdictSource:
    def __init__(self, verdict):
        self.verdict = verdict

    def assess(self, *, output, mission, principles, change_notes):
        return self.verdict


@pytest.fixture
def binder(control_plane):
    control_plane.set_direction(mission="M1", principles=("Be honest",), change_note="init")
    return DirectionBinder(LocalDirectionSource(control_plane)), control_plane


def test_given_a_wrapped_node_when_it_runs_then_the_direction_is_pulled_into_state(binder):
    bind, _cp = binder

    @pull_before(bind)
    def node(state):
        assert state["kyno_version"] == 1
        return {"output": f"served {state['kyno_mission']}"}

    update = node({})

    assert update["output"] == "served M1"
    assert update["kyno_constitution"] == "default" and update["kyno_version"] == 1


def test_given_a_pivot_when_the_next_node_enters_then_it_rebinds(binder):
    bind, control_plane = binder
    node = direction_node(bind)

    first = node({})
    control_plane.set_direction(mission="M2", change_note="pivot")
    second = node(first)

    assert (first["kyno_version"], second["kyno_version"]) == (1, 2)
    assert direction_from_state(second).mission == "M2"


def test_given_a_direction_change_when_the_graph_reaches_the_next_node_then_it_binds_the_new_one(
    binder,
):
    bind, control_plane = binder

    def work(state):
        return {"output": f"work on {state['kyno_mission']}"}

    graph = (
        StateGraph(GraphState)
        .add_node("pull", direction_node(bind))
        .add_node("work", pull_before(bind)(work))
        .add_edge(START, "pull")
        .add_edge("pull", "work")
        .add_edge("work", END)
        .compile()
    )

    first = graph.invoke({})
    control_plane.set_direction(mission="M2", change_note="pivot")
    second = graph.invoke({})

    assert first["output"] == "work on M1"
    assert second["output"] == "work on M2"


def _gated_graph(bind, gate, **kwargs):
    return (
        StateGraph(GraphState)
        .add_node("pull", direction_node(bind))
        .add_node("work", lambda state: {"output": "a draft"})
        .add_node("gate", gate_node(gate, **kwargs))
        .add_edge(START, "pull")
        .add_edge("pull", "work")
        .add_edge("work", "gate")
        .add_edge("gate", END)
        .compile(checkpointer=InMemorySaver())
    )


def test_given_an_aligned_output_when_the_gate_node_runs_then_it_passes(binder):
    bind, _cp = binder
    graph = _gated_graph(bind, RealignmentGate(StubVerdictSource(Verdict.ALIGNED), can_pause=True))

    result = graph.invoke({}, {"configurable": {"thread_id": "t1"}})

    assert result["kyno_verdict"] == "aligned" and result["kyno_checked"] is True
    assert "__interrupt__" not in result


def test_given_drift_when_the_resume_accepts_then_the_run_proceeds(binder):
    bind, _cp = binder
    graph = _gated_graph(bind, RealignmentGate(StubVerdictSource(Verdict.DRIFTED), can_pause=True))
    config = {"configurable": {"thread_id": "t2"}}

    paused = graph.invoke({}, config)
    assert paused["__interrupt__"]
    payload = paused["__interrupt__"][0].value
    assert payload["verdict"] == "drifted" and payload["version"] == 1

    resumed = graph.invoke(Command(resume={"accept": True}), config)

    assert resumed["kyno_blocked"] is False and resumed["kyno_verdict"] == "drifted"


def test_given_drift_when_the_resume_rejects_then_the_run_blocks(binder):
    bind, _cp = binder
    graph = _gated_graph(bind, RealignmentGate(StubVerdictSource(Verdict.DRIFTED), can_pause=True))
    config = {"configurable": {"thread_id": "t3"}}

    graph.invoke({}, config)
    resumed = graph.invoke(Command(resume={"accept": False}), config)

    assert resumed["kyno_blocked"] is True


def test_given_an_unjudged_output_when_the_gate_node_runs_then_it_passes_marked_unchecked(binder):
    bind, _cp = binder
    graph = _gated_graph(bind, RealignmentGate(can_pause=True))

    result = graph.invoke({}, {"configurable": {"thread_id": "t4"}})

    assert result["kyno_checked"] is False and result["kyno_blocked"] is False


def test_given_a_resume_that_does_not_say_accept_when_resuming_then_it_blocks(binder):
    """Anything but an explicit accept is a refusal; silence is not consent."""
    bind, _cp = binder
    graph = _gated_graph(bind, RealignmentGate(StubVerdictSource(Verdict.DRIFTED), can_pause=True))
    config = {"configurable": {"thread_id": "t5"}}

    graph.invoke({}, config)
    resumed = graph.invoke(Command(resume="looks fine"), config)

    assert resumed["kyno_blocked"] is True


def test_given_a_gate_that_cannot_pause_when_drift_is_found_then_it_blocks_without_interrupting(
    binder,
):
    bind, _cp = binder
    graph = _gated_graph(bind, RealignmentGate(StubVerdictSource(Verdict.DRIFTED), can_pause=False))

    result = graph.invoke({}, {"configurable": {"thread_id": "t6"}})

    assert result["kyno_blocked"] is True and "__interrupt__" not in result


def test_given_an_intervening_node_when_the_gate_runs_then_the_direction_still_reaches_it(binder):
    """The state schema must declare the kyno keys or they are dropped."""
    bind, _cp = binder
    graph = _gated_graph(bind, RealignmentGate(StubVerdictSource(Verdict.ALIGNED), can_pause=True))

    result = graph.invoke({}, {"configurable": {"thread_id": "t7"}})

    assert result["kyno_version"] == 1 and result["kyno_mission"] == "M1"


def test_given_a_schema_missing_the_kyno_keys_when_running_then_the_direction_is_lost(binder):
    """Pins why KynoState exists: without it the gate judges against v0."""
    bind, _cp = binder
    graph = (
        StateGraph(dict)
        .add_node("pull", direction_node(bind))
        .add_node("work", lambda state: {"output": "a draft"})
        .add_node("gate", gate_node(RealignmentGate(can_pause=True)))
        .add_edge(START, "pull")
        .add_edge("pull", "work")
        .add_edge("work", "gate")
        .add_edge("gate", END)
        .compile()
    )

    assert "kyno_version" not in graph.invoke({})


def test_given_an_output_key_when_the_gate_reads_then_it_uses_the_key_it_was_given():
    seen = []

    class Recorder:
        def assess(self, *, output, mission, principles, change_notes):
            seen.append(output)
            return Verdict.ALIGNED

    node = gate_node(RealignmentGate(Recorder(), can_pause=True), output_key="draft")
    node({"draft": "the draft", "output": "ignored"})

    assert seen == ["the draft"]


def test_given_a_wrapped_node_when_state_moves_then_the_rendered_block_travels_in_it(binder):
    """A persisted checkpoint must say which direction the step served."""
    bind, _cp = binder
    update = direction_node(bind)({})

    assert update["kyno_direction"].startswith(DIRECTION_MARKER)
    assert "M1" in update["kyno_direction"] and "Be honest" in update["kyno_direction"]


def test_given_the_schema_when_comparing_state_keys_then_they_are_exactly_what_it_declares():
    """A key written but not declared would be dropped between nodes."""
    update = direction_update(
        Direction(constitution="eu", version=4, mission="M", principles=("P",))
    )
    assert set(update) <= set(KynoState.__annotations__)
    assert update["kyno_constitution"] == "eu"
    assert update["kyno_principles"] == [{"title": "P", "description": ""}]


def test_given_a_direction_when_round_tripping_through_state_then_it_survives():
    original = Direction(constitution="eu", version=4, mission="M", principles=("P", "Q"))
    assert direction_from_state(direction_update(original)) == original


def test_given_state_without_kyno_keys_when_reading_then_it_is_no_direction():
    direction = direction_from_state({})
    assert direction.constitution == "default" and direction.version == 0
    assert direction.mission == "" and direction.principles == ()


def test_given_a_node_that_returns_nothing_when_it_runs_then_its_direction_is_still_recorded(
    binder,
):
    bind, _cp = binder

    @pull_before(bind)
    def node(state):
        return None

    assert node({})["kyno_version"] == 1


def test_given_the_wrapper_wrote_state_when_the_node_writes_too_then_the_node_wins(binder):
    """The node runs last, so its own keys win -- it saw the direction too."""
    bind, _cp = binder

    @pull_before(bind)
    def node(state):
        return {"kyno_mission": "as the node saw it"}

    assert node({})["kyno_mission"] == "as the node saw it"


def test_given_the_gate_node_when_it_judges_a_step_then_the_step_is_recorded(binder):
    bind, _cp = binder
    trace = RunTrace(run_id="r1")
    gate = RealignmentGate(StubVerdictSource(Verdict.ALIGNED), can_pause=True)
    state = {**direction_node(bind)({}), "output": "a draft"}

    gate_node(gate, trace=trace)(state)

    record = trace.steps[-1]
    assert record.output == "a draft" and record.verdict == "aligned"
    assert record.agent == "graph" and record.version == 1


def test_given_a_described_principle_when_checkpoint_round_tripping_then_it_survives():
    # State is persisted and re-read, so a description dropped here would
    # reach the gate node as a principle that means something else.
    from kyno.models import Principle

    original = Direction(
        constitution="eu",
        version=4,
        mission="M",
        principles=(Principle("P", "why P"),),
    )
    assert direction_from_state(direction_update(original)) == original


def test_given_a_full_binder_when_state_carries_the_block_then_it_is_the_full_document(
    control_plane,
):
    control_plane.set_direction(
        mission="M1",
        declaration="The long form.",
        principles=({"title": "Be honest", "description": "Say the hard number first."},),
        change_note="init",
    )
    binder = DirectionBinder(LocalDirectionSource(control_plane), context=FULL)

    update = direction_node(binder)({})

    assert "The long form." in update["kyno_direction"]
    assert "Say the hard number first." in update["kyno_direction"]
    assert update["kyno_context"] == FULL


def test_given_no_context_asked_when_state_carries_the_block_then_it_stays_compact(binder):
    bind, control_plane = binder
    control_plane.set_direction(declaration="The long form.", change_note="add the long form")

    update = direction_node(bind)({})

    assert "The long form." not in update["kyno_direction"]
    assert update["kyno_context"] == COMPACT


def test_given_a_context_when_round_tripping_through_state_then_it_survives():
    original = Direction(constitution="eu", version=4, mission="M", principles=("P",), context=FULL)
    assert direction_from_state(direction_update(original)) == original
