"""Direction reaches graph consumers and survives state serialization."""

import json

import pytest

pytest.importorskip("langgraph")

from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402
from langgraph.graph import END, START, StateGraph  # noqa: E402

from kyno.adapters.langgraph.nodes import (  # noqa: E402
    KynoState,
    direction_from_state,
    direction_node,
    direction_update,
    pull_before,
)
from kyno.sdk.binder import DirectionBinder  # noqa: E402
from kyno.sdk.binding import DeliveryStatus  # noqa: E402
from kyno.sdk.cell import DIRECTION_MARKER, Direction  # noqa: E402
from kyno.sdk.client import LocalDirectionSource  # noqa: E402
from kyno.wire.models import DetailLevel  # noqa: E402


class GraphState(KynoState, total=False):
    output: str
    draft: str


@pytest.fixture
def binder(control_plane):
    control_plane.set_direction(mission="M1", principles=("Be honest",), change_note="init")
    return DirectionBinder(LocalDirectionSource(control_plane)), control_plane


def _capture_graph(bind, captured, schema=GraphState):
    def capture(state):
        captured.append(direction_from_state(state))
        return {}

    return (
        StateGraph(schema)
        .add_node("pull", direction_node(bind))
        .add_node("work", lambda state: {"output": "a draft"})
        .add_node("capture", capture)
        .add_edge(START, "pull")
        .add_edge("pull", "work")
        .add_edge("work", "capture")
        .add_edge("capture", END)
        .compile(checkpointer=InMemorySaver())
    )


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
    """The node runs last, so its own keys win. It saw the direction too."""
    bind, _cp = binder

    @pull_before(bind)
    def node(state):
        return {"kyno_mission": "as the node saw it"}

    assert node({})["kyno_mission"] == "as the node saw it"


def test_given_a_described_principle_when_checkpoint_round_tripping_then_it_survives():
    from kyno.wire.models import Principle

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
    binder = DirectionBinder(LocalDirectionSource(control_plane), context=DetailLevel.FULL)

    update = direction_node(binder)({})

    assert "The long form." in update["kyno_direction"]
    assert "Say the hard number first." in update["kyno_direction"]
    assert update["kyno_context"] == DetailLevel.FULL


def test_given_no_context_asked_when_state_carries_the_block_then_it_stays_compact(binder):
    bind, control_plane = binder
    control_plane.set_direction(declaration="The long form.", change_note="add the long form")

    update = direction_node(bind)({})

    assert "The long form." not in update["kyno_direction"]
    assert update["kyno_context"] == DetailLevel.COMPACT


def test_given_complete_direction_when_round_tripping_through_state_then_all_fields_survive():
    original = Direction(
        constitution="eu",
        version=4,
        mission="M",
        principles=("P",),
        declaration="Long form",
        change_notes=("Changed support priority",),
        delta=("Mission changed.",),
        context=DetailLevel.FULL,
    )
    update = direction_update(original)

    assert update["kyno_context"] is DetailLevel.FULL
    assert direction_from_state(json.loads(json.dumps(update))) == original


def test_given_checkpoint_without_optional_direction_fields_when_reading_then_defaults_are_empty():
    state = {
        "kyno_constitution": "support",
        "kyno_version": 3,
        "kyno_mission": "Resolve issues",
        "kyno_principles": [{"title": "Be honest", "description": "Explain the outcome"}],
        "kyno_context": "full",
    }

    assert direction_from_state(state) == Direction(
        constitution="support",
        version=3,
        mission="Resolve issues",
        principles=({"title": "Be honest", "description": "Explain the outcome"},),
        context=DetailLevel.FULL,
    )


def test_given_unknown_delivery_status_when_building_direction_state_then_it_is_rejected():
    original = Direction.empty("support")
    with pytest.raises(ValueError, match="unknown-status"):
        direction_update(original, status="unknown-status")


def test_given_change_notes_when_a_checkpointed_graph_reaches_a_consumer_then_it_receives_them(
    binder,
):
    bind, _ = binder
    captured = []
    graph = _capture_graph(bind, captured)
    graph.invoke({}, {"configurable": {"thread_id": "notes"}})
    assert captured[0].change_notes == ("init",)


def test_given_an_intervening_node_when_a_consumer_runs_then_direction_reaches_it(binder):
    bind, _ = binder
    captured = []
    graph = _capture_graph(bind, captured)
    graph.invoke({}, {"configurable": {"thread_id": "direction"}})
    assert captured[0].version == 1
    assert captured[0].mission == "M1"


def test_given_a_schema_without_direction_fields_when_work_runs_then_direction_is_lost(binder):
    from typing import TypedDict

    class OutputState(TypedDict, total=False):
        output: str

    bind, _ = binder
    captured = []
    graph = _capture_graph(bind, captured, OutputState)
    result = graph.invoke({}, {"configurable": {"thread_id": "missing"}})
    assert "kyno_version" not in result
    assert captured == [Direction.empty("default")]


@pytest.mark.parametrize("context", [DetailLevel.COMPACT, DetailLevel.FULL])
def test_given_a_captured_answer_when_review_resumes_then_it_keeps_its_original_input(
    binder,
    context,
):
    class ReviewState(KynoState, total=False):
        answer_record: dict
        needs_review: bool

    bind, control_plane = binder
    bind = DirectionBinder(LocalDirectionSource(control_plane), context=context)
    bind.bind()
    control_plane.set_direction(
        declaration="Explain the support decision.",
        principles=("Be honest", "Explain the decision"),
        change_note="Add explanation",
    )
    reviewed = []

    @pull_before(bind)
    def answer(state):
        direction = direction_from_state(state)
        supplied_message = state["kyno_direction"]
        output = f"Answer for {direction.mission}"
        return {
            "answer_record": {
                "direction": direction,
                "supplied_message": supplied_message,
                "delivery_status": state["kyno_delivery_status"],
                "output": output,
            }
        }

    def refresh(state):
        control_plane.set_direction(mission="M2", change_note="pivot")
        return direction_node(bind)(state)

    def review(state):
        reviewed.append(state["answer_record"])
        return {
            "needs_review": "refund has been issued" in state["answer_record"]["output"].lower()
        }

    graph = (
        StateGraph(ReviewState)
        .add_node("answer", answer)
        .add_node("refresh", refresh)
        .add_node("review", review)
        .add_edge(START, "answer")
        .add_edge("answer", "refresh")
        .add_edge("refresh", "review")
        .add_edge("review", END)
        .compile(checkpointer=InMemorySaver(), interrupt_before=["review"])
    )

    config = {"configurable": {"thread_id": f"review-{context.value}"}}
    graph.invoke({}, config)
    saved = graph.get_state(config).values
    original = saved["answer_record"]
    assert reviewed == []
    result = graph.invoke(None, config)

    assert result["kyno_version"] == 3
    assert reviewed[0] == original
    assert reviewed[0]["direction"].version == 2
    assert reviewed[0]["direction"].mission == "M1"
    assert reviewed[0]["direction"].declaration == "Explain the support decision."
    assert tuple(reviewed[0]["direction"].change_notes) == ("Add explanation",)
    assert reviewed[0]["direction"].delta
    assert reviewed[0]["direction"].context == context
    assert reviewed[0]["supplied_message"] == reviewed[0]["direction"].render()
    assert reviewed[0]["output"] == "Answer for M1"
    assert reviewed[0]["delivery_status"] is DeliveryStatus.CURRENT
    assert result["needs_review"] is False
