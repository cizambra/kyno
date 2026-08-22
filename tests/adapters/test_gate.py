from kyno.models import Principle
from kyno.sdk.cell import Direction
from kyno.sdk.gate import (
    NO_SOURCE,
    SOURCE_ERROR,
    UNKNOWN_VERDICT,
    Action,
    RealignmentGate,
    Verdict,
)
from kyno.sdk.policy import (
    DRIFT_BLOCKED,
    DRIFT_PAUSED,
    PAUSE_UNSUPPORTED,
    UNCHECKED,
    GatePolicy,
    RecordingSink,
)

DIRECTION = Direction(
    constitution="eu", version=4, mission="Ship trustworthy lending", principles=("Be honest",)
)


class StubVerdictSource:
    def __init__(self, verdict=None, error: Exception | None = None):
        self.verdict = verdict
        self.error = error
        self.seen: list[dict] = []

    def assess(self, *, output, mission, principles, change_notes):
        self.seen.append(
            {
                "output": output,
                "mission": mission,
                "principles": principles,
                "change_notes": change_notes,
            }
        )
        if self.error is not None:
            raise self.error
        return self.verdict


def test_aligned_output_proceeds_checked():
    gate = RealignmentGate(StubVerdictSource(Verdict.ALIGNED))
    decision = gate.review(output="fine", direction=DIRECTION)
    assert decision.action is Action.PROCEED and decision.checked is True
    assert decision.verdict is Verdict.ALIGNED


def test_the_source_sees_the_direction_it_should_judge_against():
    source = StubVerdictSource(Verdict.ALIGNED)
    RealignmentGate(source).review(output="draft", direction=DIRECTION)
    assert source.seen == [
        {
            "output": "draft",
            "mission": "Ship trustworthy lending",
            "principles": (Principle("Be honest"),),
            "change_notes": (),
        }
    ]


def test_no_source_proceeds_unchecked_and_says_so():
    sink = RecordingSink()
    decision = RealignmentGate(telemetry=sink).review(output="anything", direction=DIRECTION)

    assert decision.action is Action.PROCEED
    assert decision.checked is False and decision.reason == NO_SOURCE
    assert decision.constitution == "eu" and decision.version == 4
    assert [e.kind for e in sink.events] == [UNCHECKED]


def test_a_broken_judge_proceeds_unchecked_not_blocked():
    sink = RecordingSink()
    gate = RealignmentGate(StubVerdictSource(error=TimeoutError("judge down")), telemetry=sink)

    decision = gate.review(output="anything", direction=DIRECTION)

    assert decision.action is Action.PROCEED and decision.reason == SOURCE_ERROR
    assert sink.events[0].detail.startswith("judge down") or "judge down" in sink.events[0].detail


def test_fail_closed_blocks_only_the_gate_that_opted_in():
    strict = RealignmentGate(policy=GatePolicy(fail_closed=True))
    lenient = RealignmentGate()

    assert strict.review(output="x", direction=DIRECTION).action is Action.BLOCK
    assert lenient.review(output="x", direction=DIRECTION).action is Action.PROCEED


def test_an_unknown_verdict_from_a_working_judge_follows_the_same_policy():
    gate = RealignmentGate(StubVerdictSource(Verdict.UNKNOWN))
    decision = gate.review(output="x", direction=DIRECTION)
    assert decision.action is Action.PROCEED and decision.checked is False


def test_drift_blocks_where_the_framework_cannot_pause():
    sink = RecordingSink()
    gate = RealignmentGate(StubVerdictSource(Verdict.DRIFTED), telemetry=sink, can_pause=False)

    decision = gate.review(output="off-mission", direction=DIRECTION)

    assert decision.action is Action.BLOCK and decision.checked is True
    assert {e.kind for e in sink.events} == {DRIFT_BLOCKED, PAUSE_UNSUPPORTED}


def test_drift_pauses_where_the_framework_can():
    sink = RecordingSink()
    gate = RealignmentGate(StubVerdictSource(Verdict.DRIFTED), telemetry=sink, can_pause=True)

    decision = gate.review(output="off-mission", direction=DIRECTION)

    assert decision.action is Action.PAUSE and decision.checked is True
    assert [e.kind for e in sink.events] == [DRIFT_PAUSED]


def test_drift_still_blocks_under_a_fail_open_policy():
    # Fail-open governs the ABSENCE of a judgment; a real DRIFTED verdict is
    # a judgment and must not be waved through.
    gate = RealignmentGate(StubVerdictSource(Verdict.DRIFTED), policy=GatePolicy())
    assert gate.review(output="x", direction=DIRECTION).action is Action.BLOCK


def test_decision_serializes_for_a_trace():
    decision = RealignmentGate().review(output="x", direction=DIRECTION)
    assert decision.to_dict() == {
        "action": "proceed",
        "verdict": "unknown",
        "checked": False,
        "reason": NO_SOURCE,
        "constitution": "eu",
        "version": 4,
    }


def test_an_aligned_review_stays_quiet():
    """Telemetry marks degraded and blocked work; routine passes are noise."""
    sink = RecordingSink()
    RealignmentGate(StubVerdictSource(Verdict.ALIGNED), telemetry=sink).review(
        output="fine", direction=DIRECTION
    )
    assert sink.events == []


def test_a_judge_that_answers_with_a_non_verdict_is_treated_as_no_answer():
    gate = RealignmentGate(StubVerdictSource(verdict="looks fine to me"))
    decision = gate.review(output="x", direction=DIRECTION)
    assert decision.reason == UNKNOWN_VERDICT
    assert decision.action is Action.PROCEED and decision.checked is False


def test_a_fail_closed_gate_blocks_a_broken_judge():
    gate = RealignmentGate(
        StubVerdictSource(error=TimeoutError("judge down")), policy=GatePolicy(fail_closed=True)
    )
    decision = gate.review(output="x", direction=DIRECTION)
    assert decision.action is Action.BLOCK and decision.reason == SOURCE_ERROR


def test_fail_closed_does_not_turn_a_pausable_drift_into_a_block():
    """Pause preserves the run for a human; fail-closed is about no answer."""
    gate = RealignmentGate(
        StubVerdictSource(Verdict.DRIFTED), policy=GatePolicy(fail_closed=True), can_pause=True
    )
    assert gate.review(output="x", direction=DIRECTION).action is Action.PAUSE


def test_a_review_before_any_direction_is_set_is_still_recorded():
    """A crew can start before anyone sets direction; the trace must say so."""
    sink = RecordingSink()
    gate = RealignmentGate(StubVerdictSource(Verdict.ALIGNED), telemetry=sink)

    decision = gate.review(output="x", direction=Direction.empty("default"))

    assert decision.constitution == "default" and decision.version == 0


def test_a_blocked_drift_serializes_the_whole_decision():
    gate = RealignmentGate(StubVerdictSource(Verdict.DRIFTED))
    assert gate.review(output="x", direction=DIRECTION).to_dict() == {
        "action": "block",
        "verdict": "drifted",
        "checked": True,
        "reason": "drifted",
        "constitution": "eu",
        "version": 4,
    }
