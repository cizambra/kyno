from datetime import UTC

from kyno.models import Principle
from kyno.sdk.cell import Direction
from kyno.sdk.gate import Action, GateDecision, Verdict
from kyno.sdk.trace import SERVES_DIRECTION_FIELDS, RunTrace

DIRECTION = Direction(
    constitution="eu", version=4, mission="Ship trustworthy lending", principles=("Be honest",)
)


def test_a_step_record_pins_the_direction_it_served():
    trace = RunTrace(run_id="r1", goal="Launch in the EU")
    record = trace.record_step(
        agent="researcher", goal="Find lenders", output="a list", direction=DIRECTION
    )

    assert record.constitution == "eu" and record.version == 4
    assert record.mission == "Ship trustworthy lending"
    assert record.principles == (Principle("Be honest"),)
    assert record.agent == "researcher" and record.output == "a list"
    assert record.verdict == Verdict.UNKNOWN.value and record.checked is False


def test_a_gate_decision_lands_on_the_record():
    trace = RunTrace(run_id="r1")
    decision = GateDecision(
        action=Action.PROCEED,
        verdict=Verdict.ALIGNED,
        checked=True,
        reason="aligned",
        constitution="eu",
        version=4,
    )
    record = trace.record_step(
        agent="writer", goal="Draft", output="text", direction=DIRECTION, decision=decision
    )
    assert record.verdict == "aligned" and record.checked is True


def test_step_ids_are_unique_and_ordered():
    trace = RunTrace(run_id="r1")
    ids = [
        trace.record_step(agent="a", goal="g", output="o", direction=DIRECTION).step_id
        for _ in range(3)
    ]
    assert len(set(ids)) == 3
    assert [s.step_id for s in trace.steps] == ids


def test_the_atom_fields_are_all_present_in_the_serialized_step():
    trace = RunTrace(run_id="r1")
    trace.record_step(agent="a", goal="g", output="o", direction=DIRECTION)
    payload = trace.to_dict()

    assert payload["run_id"] == "r1"
    step = payload["steps"][0]
    for field_name in SERVES_DIRECTION_FIELDS:
        assert field_name in step, field_name


def test_an_unchecked_run_is_visible_after_the_fact():
    trace = RunTrace(run_id="r1")
    trace.record_step(agent="a", goal="g", output="o", direction=DIRECTION)
    assert [s.step_id for s in trace.steps if not s.checked]


def test_two_runs_number_their_steps_independently():
    """A shared counter would make step ids collide across concurrent runs."""
    first = RunTrace(run_id="r1")
    second = RunTrace(run_id="r2")

    first.record_step(agent="a", goal="g", output="o", direction=DIRECTION)
    record = second.record_step(agent="a", goal="g", output="o", direction=DIRECTION)

    assert record.step_id == "r2-s1"


def test_a_caller_supplied_step_id_wins():
    """Hosts that already have their own step ids should keep using them."""
    trace = RunTrace(run_id="r1")
    record = trace.record_step(
        agent="a", goal="g", output="o", direction=DIRECTION, step_id="task-7"
    )
    assert record.step_id == "task-7" and trace.steps[0].step_id == "task-7"


def test_blocked_work_is_recorded_not_dropped():
    trace = RunTrace(run_id="r1")
    decision = GateDecision(
        action=Action.BLOCK,
        verdict=Verdict.DRIFTED,
        checked=True,
        reason="drifted",
        constitution="eu",
        version=4,
    )
    record = trace.record_step(
        agent="w", goal="g", output="off-mission", direction=DIRECTION, decision=decision
    )
    assert record.verdict == "drifted" and record.checked is True


def test_a_step_is_timestamped_in_utc():
    trace = RunTrace(run_id="r1")
    record = trace.record_step(agent="a", goal="g", output="o", direction=DIRECTION)
    assert record.occurred_at.tzinfo is not None
    assert record.occurred_at.utcoffset() == UTC.utcoffset(None)


def test_a_serialized_run_is_json_shaped_and_ordered():
    trace = RunTrace(run_id="r1", goal="Launch in the EU")
    trace.record_step(agent="researcher", goal="Find lenders", output="a list", direction=DIRECTION)
    trace.record_step(agent="writer", goal="Draft", output="text", direction=DIRECTION)

    payload = trace.to_dict()

    assert payload["goal"] == "Launch in the EU"
    assert [s["agent"] for s in payload["steps"]] == ["researcher", "writer"]
    assert payload["steps"][0]["principles"] == [{"title": "Be honest", "description": ""}]
    assert isinstance(payload["steps"][0]["occurred_at"], str)
