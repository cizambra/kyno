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
from kyno.sdk.binding import BindingStatus  # noqa: E402
from kyno.sdk.cell import DIRECTION_MARKER, Direction  # noqa: E402
from kyno.sdk.client import LocalDirectionSource  # noqa: E402
from kyno.wire.models import DetailLevel  # noqa: E402


class GraphState(KynoState, total=False):
    output: str
    draft: str


@pytest.fixture
def binder(control_plane):
    control_plane.apply_direction(mission="M1", principles=("Be honest",), change_note="init")
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


def test_given_direction_when_pull_before_runs_then_work_receives_current_direction(binder):
    bind, _cp = binder

    @pull_before(bind)
    def node(state):
        assert state["kyno_version"] == 1
        return {"output": f"served {state['kyno_mission']}"}

    update = node({})

    assert update["output"] == "served M1"
    assert update["kyno_constitution_key"] == "default"
    assert update["kyno_version"] == 1


def test_given_new_direction_when_direction_node_runs_again_then_state_has_new_version(binder):
    bind, control_plane = binder
    node = direction_node(bind)

    first = node({})
    control_plane.apply_direction(mission="M2", change_note="pivot")
    second = node(first)

    assert (first["kyno_version"], second["kyno_version"]) == (1, 2)
    assert direction_from_state(second).mission == "M2"


def test_given_new_direction_when_pull_before_runs_in_graph_then_work_uses_new_mission(
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
    control_plane.apply_direction(mission="M2", change_note="pivot")
    second = graph.invoke({})

    assert first["output"] == "work on M1"
    assert second["output"] == "work on M2"


def test_given_direction_when_direction_node_runs_then_block_has_mission_and_principles(binder):
    """A persisted checkpoint must say which direction the step served."""
    bind, _cp = binder
    update = direction_node(bind)({})

    assert update["kyno_direction"].startswith(DIRECTION_MARKER)
    assert "M1" in update["kyno_direction"] and "Be honest" in update["kyno_direction"]


def test_given_direction_when_direction_update_runs_then_keys_exist_in_KynoState():
    """A key written but not declared would be dropped between nodes."""
    update = direction_update(
        Direction(constitution_key="eu", version=4, mission="M", principles=("P",))
    )
    assert set(update) <= set(KynoState.__annotations__)
    assert update["kyno_constitution_key"] == "eu"
    assert update["kyno_principles"] == [{"title": "P", "description": ""}]


def test_given_updated_state_when_direction_from_state_runs_then_original_direction_returns():
    original = Direction(constitution_key="eu", version=4, mission="M", principles=("P", "Q"))
    assert direction_from_state(direction_update(original)) == original


def test_given_empty_state_when_direction_from_state_runs_then_default_version_zero_returns():
    direction = direction_from_state({})
    assert direction.constitution_key == "default"
    assert direction.version == 0
    assert direction.mission == ""
    assert direction.principles == ()


def test_given_work_returning_none_when_pull_before_runs_then_direction_remains_in_state(
    binder,
):
    bind, _cp = binder

    @pull_before(bind)
    def node(state):
        return None

    assert node({})["kyno_version"] == 1


def test_given_work_overriding_mission_when_pull_before_runs_then_work_value_wins(binder):
    """The node runs last, so its own keys win. It saw the direction too."""
    bind, _cp = binder

    @pull_before(bind)
    def node(state):
        return {"kyno_mission": "as the node saw it"}

    assert node({})["kyno_mission"] == "as the node saw it"


def test_given_principle_description_when_direction_from_state_runs_then_description_is_kept():
    from kyno.wire.models import Principle

    original = Direction(
        constitution_key="eu",
        version=4,
        mission="M",
        principles=(Principle("P", "why P"),),
    )
    assert direction_from_state(direction_update(original)) == original


def test_given_full_detail_when_direction_node_runs_then_block_has_declaration_and_descriptions(
    control_plane,
):
    control_plane.apply_direction(
        mission="M1",
        declaration="The long form.",
        principles=({"title": "Be honest", "description": "Say the hard number first."},),
        change_note="init",
    )
    binder = DirectionBinder(LocalDirectionSource(control_plane), detail=DetailLevel.FULL)

    update = direction_node(binder)({})

    assert "The long form." in update["kyno_direction"]
    assert "Say the hard number first." in update["kyno_direction"]
    assert update["kyno_detail"] == DetailLevel.FULL


def test_given_default_detail_when_direction_node_runs_then_block_omits_declaration(binder):
    bind, control_plane = binder
    control_plane.apply_direction(declaration="The long form.", change_note="add the long form")

    update = direction_node(bind)({})

    assert "The long form." not in update["kyno_direction"]
    assert update["kyno_detail"] == DetailLevel.COMPACT


def test_given_json_state_when_direction_from_state_runs_then_all_fields_are_restored():
    original = Direction(
        constitution_key="eu",
        version=4,
        mission="M",
        principles=("P",),
        declaration="Long form",
        change_notes=("Changed support priority",),
        delta=("Mission changed.",),
        detail=DetailLevel.FULL,
    )
    update = direction_update(original)

    assert update["kyno_detail"] is DetailLevel.FULL
    assert direction_from_state(json.loads(json.dumps(update))) == original


def test_given_missing_optional_fields_when_direction_from_state_runs_then_empty_defaults_apply():
    state = {
        "kyno_constitution_key": "support",
        "kyno_version": 3,
        "kyno_mission": "Resolve issues",
        "kyno_principles": [{"title": "Be honest", "description": "Explain the outcome"}],
        "kyno_detail": "full",
    }

    assert direction_from_state(state) == Direction(
        constitution_key="support",
        version=3,
        mission="Resolve issues",
        principles=({"title": "Be honest", "description": "Explain the outcome"},),
        detail=DetailLevel.FULL,
    )


def test_given_unknown_status_when_direction_update_runs_then_ValueError_is_raised():
    original = Direction.empty("support")
    with pytest.raises(ValueError, match="unknown-status"):
        direction_update(original, status="unknown-status")


def test_given_change_notes_when_direction_node_runs_then_consumer_receives_notes(
    binder,
):
    bind, _ = binder
    captured = []
    graph = _capture_graph(bind, captured)
    graph.invoke({}, {"configurable": {"thread_id": "notes"}})
    assert captured[0].change_notes == ("init",)


def test_given_intervening_work_when_direction_node_runs_then_consumer_receives_direction(binder):
    bind, _ = binder
    captured = []
    graph = _capture_graph(bind, captured)
    graph.invoke({}, {"configurable": {"thread_id": "direction"}})
    assert captured[0].version == 1
    assert captured[0].mission == "M1"


def test_given_schema_without_KynoState_when_direction_node_runs_then_graph_drops_direction(binder):
    from typing import TypedDict

    class OutputState(TypedDict, total=False):
        output: str

    bind, _ = binder
    captured = []
    graph = _capture_graph(bind, captured, OutputState)
    result = graph.invoke({}, {"configurable": {"thread_id": "missing"}})
    assert "kyno_version" not in result
    assert captured == [Direction.empty("default")]


@pytest.mark.parametrize("detail", [DetailLevel.COMPACT, DetailLevel.FULL])
def test_given_direction_node_refresh_when_review_resumes_then_saved_answer_keeps_prior_direction(
    binder,
    detail,
):
    class ReviewState(KynoState, total=False):
        answer_record: dict
        needs_review: bool

    bind, control_plane = binder
    bind = DirectionBinder(LocalDirectionSource(control_plane), detail=detail)
    bind.bind()
    control_plane.apply_direction(
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
                "binding_status": state["kyno_binding_status"],
                "output": output,
            }
        }

    def refresh(state):
        control_plane.apply_direction(mission="M2", change_note="pivot")
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

    config = {"configurable": {"thread_id": f"review-{detail.value}"}}
    graph.invoke({}, config)
    saved = graph.get_state(config).values
    original = saved["answer_record"]
    assert reviewed == []
    result = graph.invoke(None, config)

    assert result["kyno_version"] == 3
    assert reviewed[0] == original
    assert reviewed[0]["direction"].version == 2
    assert reviewed[0]["direction"].mission == "M1"
    assert reviewed[0]["direction"].declaration == (
        "Explain the support decision." if detail is DetailLevel.FULL else ""
    )
    assert tuple(reviewed[0]["direction"].change_notes) == ("Add explanation",)
    assert reviewed[0]["direction"].delta
    assert reviewed[0]["direction"].detail == detail
    assert reviewed[0]["supplied_message"] == reviewed[0]["direction"].render()
    assert reviewed[0]["output"] == "Answer for M1"
    assert reviewed[0]["binding_status"] is BindingStatus.PULLED
    assert result["needs_review"] is False
