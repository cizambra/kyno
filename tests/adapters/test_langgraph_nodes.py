import pytest

pytest.importorskip("langgraph")

from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402
from langgraph.graph import END, START, StateGraph  # noqa: E402
from langgraph.types import Command  # noqa: E402

from kyno.adapters.core.binder import DirectionBinder  # noqa: E402
from kyno.adapters.core.cell import (  # noqa: E402
    COMPACT,
    DIRECTION_MARKER,
    FULL,
    Direction,
)
from kyno.adapters.core.client import LocalDirectionSource  # noqa: E402
from kyno.adapters.core.gate import RealignmentGate, Verdict  # noqa: E402
from kyno.adapters.core.trace import RunTrace  # noqa: E402
from kyno.adapters.langgraph.nodes import (  # noqa: E402
    KynoState,
    direction_from_state,
    direction_node,
    direction_update,
    gate_node,
    pull_before,
)


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


def test_pull_before_writes_the_direction_into_state(binder):
    bind, _cp = binder

    @pull_before(bind)
    def node(state):
        assert state["kyno_version"] == 1
        return {"output": f"served {state['kyno_mission']}"}

    update = node({})

    assert update["output"] == "served M1"
    assert update["kyno_constitution"] == "default" and update["kyno_version"] == 1


def test_each_node_entry_rebinds_after_a_pivot(binder):
    bind, control_plane = binder
    node = direction_node(bind)

    first = node({})
    control_plane.set_direction(mission="M2", change_note="pivot")
    second = node(first)

    assert (first["kyno_version"], second["kyno_version"]) == (1, 2)
    assert direction_from_state(second).mission == "M2"


def test_a_graph_binds_the_new_direction_at_the_next_node(binder):
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


def test_an_aligned_output_passes_the_gate_node(binder):
    bind, _cp = binder
    graph = _gated_graph(bind, RealignmentGate(StubVerdictSource(Verdict.ALIGNED), can_pause=True))

    result = graph.invoke({}, {"configurable": {"thread_id": "t1"}})

    assert result["kyno_verdict"] == "aligned" and result["kyno_checked"] is True
    assert "__interrupt__" not in result


def test_drift_interrupts_and_an_accepting_resume_proceeds(binder):
    bind, _cp = binder
    graph = _gated_graph(bind, RealignmentGate(StubVerdictSource(Verdict.DRIFTED), can_pause=True))
    config = {"configurable": {"thread_id": "t2"}}

    paused = graph.invoke({}, config)
    assert paused["__interrupt__"]
    payload = paused["__interrupt__"][0].value
    assert payload["verdict"] == "drifted" and payload["version"] == 1

    resumed = graph.invoke(Command(resume={"accept": True}), config)

    assert resumed["kyno_blocked"] is False and resumed["kyno_verdict"] == "drifted"


def test_a_rejecting_resume_blocks(binder):
    bind, _cp = binder
    graph = _gated_graph(bind, RealignmentGate(StubVerdictSource(Verdict.DRIFTED), can_pause=True))
    config = {"configurable": {"thread_id": "t3"}}

    graph.invoke({}, config)
    resumed = graph.invoke(Command(resume={"accept": False}), config)

    assert resumed["kyno_blocked"] is True


def test_an_unjudged_output_passes_marked_unchecked(binder):
    bind, _cp = binder
    graph = _gated_graph(bind, RealignmentGate(can_pause=True))

    result = graph.invoke({}, {"configurable": {"thread_id": "t4"}})

    assert result["kyno_checked"] is False and result["kyno_blocked"] is False


def test_a_resume_that_does_not_say_accept_blocks(binder):
    """Anything but an explicit accept is a refusal; silence is not consent."""
    bind, _cp = binder
    graph = _gated_graph(bind, RealignmentGate(StubVerdictSource(Verdict.DRIFTED), can_pause=True))
    config = {"configurable": {"thread_id": "t5"}}

    graph.invoke({}, config)
    resumed = graph.invoke(Command(resume="looks fine"), config)

    assert resumed["kyno_blocked"] is True


def test_a_gate_that_cannot_pause_blocks_without_interrupting(binder):
    bind, _cp = binder
    graph = _gated_graph(bind, RealignmentGate(StubVerdictSource(Verdict.DRIFTED), can_pause=False))

    result = graph.invoke({}, {"configurable": {"thread_id": "t6"}})

    assert result["kyno_blocked"] is True and "__interrupt__" not in result


def test_the_direction_reaches_the_gate_across_an_intervening_node(binder):
    """The state schema must declare the kyno keys or they are dropped."""
    bind, _cp = binder
    graph = _gated_graph(bind, RealignmentGate(StubVerdictSource(Verdict.ALIGNED), can_pause=True))

    result = graph.invoke({}, {"configurable": {"thread_id": "t7"}})

    assert result["kyno_version"] == 1 and result["kyno_mission"] == "M1"


def test_a_state_schema_missing_the_kyno_keys_loses_the_direction(binder):
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


def test_the_gate_reads_the_output_key_it_was_given():
    seen = []

    class Recorder:
        def assess(self, *, output, mission, principles, change_notes):
            seen.append(output)
            return Verdict.ALIGNED

    node = gate_node(RealignmentGate(Recorder(), can_pause=True), output_key="draft")
    node({"draft": "the draft", "output": "ignored"})

    assert seen == ["the draft"]


def test_the_rendered_block_travels_in_state(binder):
    """A persisted checkpoint must say which direction the step served."""
    bind, _cp = binder
    update = direction_node(bind)({})

    assert update["kyno_direction"].startswith(DIRECTION_MARKER)
    assert "M1" in update["kyno_direction"] and "Be honest" in update["kyno_direction"]


def test_the_state_keys_are_exactly_what_the_schema_declares():
    """A key written but not declared would be dropped between nodes."""
    update = direction_update(
        Direction(constitution="eu", version=4, mission="M", principles=("P",))
    )
    assert set(update) <= set(KynoState.__annotations__)
    assert update["kyno_constitution"] == "eu"
    assert update["kyno_principles"] == [{"title": "P", "description": ""}]


def test_a_direction_survives_a_round_trip_through_state():
    original = Direction(constitution="eu", version=4, mission="M", principles=("P", "Q"))
    assert direction_from_state(direction_update(original)) == original


def test_state_without_any_kyno_keys_reads_as_no_direction():
    direction = direction_from_state({})
    assert direction.constitution == "default" and direction.version == 0
    assert direction.mission == "" and direction.principles == ()


def test_a_node_that_returns_nothing_still_records_its_direction(binder):
    bind, _cp = binder

    @pull_before(bind)
    def node(state):
        return None

    assert node({})["kyno_version"] == 1


def test_a_node_may_overwrite_what_the_wrapper_wrote(binder):
    """The node runs last, so its own keys win -- it saw the direction too."""
    bind, _cp = binder

    @pull_before(bind)
    def node(state):
        return {"kyno_mission": "as the node saw it"}

    assert node({})["kyno_mission"] == "as the node saw it"


def test_the_gate_node_records_the_step_it_judged(binder):
    bind, _cp = binder
    trace = RunTrace(run_id="r1")
    gate = RealignmentGate(StubVerdictSource(Verdict.ALIGNED), can_pause=True)
    state = {**direction_node(bind)({}), "output": "a draft"}

    gate_node(gate, trace=trace)(state)

    record = trace.steps[-1]
    assert record.output == "a draft" and record.verdict == "aligned"
    assert record.agent == "graph" and record.version == 1


def test_a_principles_description_survives_a_checkpoint_round_trip():
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


def test_the_block_in_state_carries_the_full_document_when_the_binder_says_so(control_plane):
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


def test_the_block_in_state_stays_compact_by_default(binder):
    bind, control_plane = binder
    control_plane.set_direction(declaration="The long form.", change_note="add the long form")

    update = direction_node(bind)({})

    assert "The long form." not in update["kyno_direction"]
    assert update["kyno_context"] == COMPACT


def test_the_context_survives_a_round_trip_through_state():
    original = Direction(constitution="eu", version=4, mission="M", principles=("P",), context=FULL)
    assert direction_from_state(direction_update(original)) == original
