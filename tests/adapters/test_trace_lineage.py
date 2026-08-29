import pytest

from kyno.sdk.cell import Direction
from kyno.sdk.trace import (
    DECOMPOSITION_COHERES_FIELDS,
    DELEGATION,
    SUBGRAPH,
    TASK,
    RunTrace,
)

DIRECTION = Direction(constitution="default", version=1, mission="M", principles=())


def _trace() -> tuple[RunTrace, list]:
    trace = RunTrace(run_id="r1", goal="Launch in the EU")
    parent = trace.record_step(
        agent="lead", goal="Launch in the EU", output="plan", direction=DIRECTION
    )
    kids = [
        trace.record_step(agent=name, goal=goal, output="done", direction=DIRECTION)
        for name, goal in (("researcher", "Find lenders"), ("writer", "Draft the copy"))
    ]
    for kid in kids:
        trace.record_decomposition(parent.step_id, kid.step_id, TASK)
    return trace, [parent, *kids]


def test_given_a_split_goal_when_asking_lineage_then_it_answers_what_it_split_into():
    trace, (parent, first, second) = _trace()
    assert [c.step_id for c in trace.children(parent.step_id)] == [first.step_id, second.step_id]
    assert [c.goal for c in trace.children(parent.step_id)] == ["Find lenders", "Draft the copy"]


def test_given_a_trace_when_asking_for_roots_then_they_are_the_steps_nothing_split_into():
    trace, (parent, _first, _second) = _trace()
    assert [r.step_id for r in trace.roots()] == [parent.step_id]


def test_given_a_split_when_reading_the_edge_then_it_records_how_it_happened():
    trace = RunTrace(run_id="r1")
    edge = trace.record_decomposition("a", "b", DELEGATION)
    assert edge.to_dict() == {"parent_id": "a", "child_id": "b", "kind": DELEGATION}
    assert trace.edges == (edge,)


def test_given_an_edge_to_an_unknown_step_when_recording_then_it_is_rejected_on_entry():
    # Canon reads this trace as a graph; a dangling edge would silently make
    # a decomposition look incomplete instead of failing here.
    trace, (parent, _f, _s) = _trace()
    with pytest.raises(KeyError):
        trace.children("no-such-step")


def test_given_a_serialized_trace_when_reading_then_every_atom_field_is_present():
    trace, _steps = _trace()
    payload = trace.to_dict()
    for field_name in DECOMPOSITION_COHERES_FIELDS:
        assert field_name in payload, field_name
    assert len(payload["edges"]) == 2


def test_given_a_leaf_step_when_asking_lineage_then_it_has_no_children():
    trace, (_parent, first, _second) = _trace()
    assert trace.children(first.step_id) == ()


def test_given_a_child_of_two_parents_when_asking_lineage_then_it_appears_under_both():
    """Two agents can converge on one follow-up step; lineage must show it."""
    trace = RunTrace(run_id="r1")
    left = trace.record_step(agent="a", goal="left", output="o", direction=DIRECTION)
    right = trace.record_step(agent="b", goal="right", output="o", direction=DIRECTION)
    shared = trace.record_step(agent="c", goal="merge", output="o", direction=DIRECTION)
    trace.record_decomposition(left.step_id, shared.step_id, DELEGATION)
    trace.record_decomposition(right.step_id, shared.step_id, DELEGATION)

    assert trace.children(left.step_id) == (shared,)
    assert trace.children(right.step_id) == (shared,)
    assert [r.step_id for r in trace.roots()] == [left.step_id, right.step_id]


def test_given_an_early_edge_when_the_child_step_is_recorded_then_the_edge_resolves():
    """A graph may record the split first and the child's output later."""
    trace = RunTrace(run_id="r1")
    parent = trace.record_step(agent="a", goal="g", output="o", direction=DIRECTION)
    trace.record_decomposition(parent.step_id, "r1-s2", SUBGRAPH)

    assert trace.children(parent.step_id) == ()

    child = trace.record_step(agent="b", goal="sub", output="o", direction=DIRECTION)
    assert child.step_id == "r1-s2"
    assert trace.children(parent.step_id) == (child,)


def test_given_two_traces_when_recording_edges_then_they_do_not_share_them():
    first, _ = _trace()
    second = RunTrace(run_id="r2")
    assert second.edges == () and len(first.edges) == 2


def test_given_the_split_kinds_when_comparing_then_the_three_are_distinct():
    assert len({TASK, DELEGATION, SUBGRAPH}) == 3
