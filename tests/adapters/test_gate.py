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


def test_given_an_aligned_output_when_gating_then_it_proceeds_checked():
    gate = RealignmentGate(StubVerdictSource(Verdict.ALIGNED))
    decision = gate.review(output="fine", direction=DIRECTION)
    assert decision.action is Action.PROCEED and decision.checked is True
    assert decision.verdict is Verdict.ALIGNED


def test_given_the_judge_source_when_gating_then_it_sees_the_direction_to_judge_against():
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


def test_given_no_judge_source_when_gating_then_it_proceeds_unchecked_and_says_so():
    sink = RecordingSink()
    decision = RealignmentGate(telemetry=sink).review(output="anything", direction=DIRECTION)

    assert decision.action is Action.PROCEED
    assert decision.checked is False and decision.reason == NO_SOURCE
    assert decision.constitution == "eu" and decision.version == 4
    assert [e.kind for e in sink.events] == [UNCHECKED]


def test_given_a_broken_judge_when_gating_then_it_proceeds_unchecked_not_blocked():
    sink = RecordingSink()
    gate = RealignmentGate(StubVerdictSource(error=TimeoutError("judge down")), telemetry=sink)

    decision = gate.review(output="anything", direction=DIRECTION)

    assert decision.action is Action.PROCEED and decision.reason == SOURCE_ERROR
    assert sink.events[0].detail.startswith("judge down") or "judge down" in sink.events[0].detail


def test_given_fail_closed_when_gating_then_only_the_opted_in_gate_blocks():
    strict = RealignmentGate(policy=GatePolicy(fail_closed=True))
    lenient = RealignmentGate()

    assert strict.review(output="x", direction=DIRECTION).action is Action.BLOCK
    assert lenient.review(output="x", direction=DIRECTION).action is Action.PROCEED


def test_given_an_unknown_verdict_when_gating_then_the_no_answer_policy_applies():
    gate = RealignmentGate(StubVerdictSource(Verdict.UNKNOWN))
    decision = gate.review(output="x", direction=DIRECTION)
    assert decision.action is Action.PROCEED and decision.checked is False


def test_given_drift_when_the_framework_cannot_pause_then_it_blocks():
    sink = RecordingSink()
    gate = RealignmentGate(StubVerdictSource(Verdict.DRIFTED), telemetry=sink, can_pause=False)

    decision = gate.review(output="off-mission", direction=DIRECTION)

    assert decision.action is Action.BLOCK and decision.checked is True
    assert {e.kind for e in sink.events} == {DRIFT_BLOCKED, PAUSE_UNSUPPORTED}


def test_given_drift_when_the_framework_can_pause_then_it_pauses():
    sink = RecordingSink()
    gate = RealignmentGate(StubVerdictSource(Verdict.DRIFTED), telemetry=sink, can_pause=True)

    decision = gate.review(output="off-mission", direction=DIRECTION)

    assert decision.action is Action.PAUSE and decision.checked is True
    assert [e.kind for e in sink.events] == [DRIFT_PAUSED]


def test_given_a_fail_open_policy_when_drift_is_found_then_it_still_blocks():
    # Fail-open governs the ABSENCE of a judgment; a real DRIFTED verdict is
    # a judgment and must not be waved through.
    gate = RealignmentGate(StubVerdictSource(Verdict.DRIFTED), policy=GatePolicy())
    assert gate.review(output="x", direction=DIRECTION).action is Action.BLOCK


def test_given_a_decision_when_serializing_for_a_trace_then_it_round_trips():
    decision = RealignmentGate().review(output="x", direction=DIRECTION)
    assert decision.to_dict() == {
        "action": "proceed",
        "verdict": "unknown",
        "checked": False,
        "reason": NO_SOURCE,
        "constitution": "eu",
        "version": 4,
    }


def test_given_an_aligned_review_when_gating_then_it_stays_quiet():
    """Telemetry marks degraded and blocked work; routine passes are noise."""
    sink = RecordingSink()
    RealignmentGate(StubVerdictSource(Verdict.ALIGNED), telemetry=sink).review(
        output="fine", direction=DIRECTION
    )
    assert sink.events == []


def test_given_a_non_verdict_answer_when_gating_then_it_is_treated_as_no_answer():
    gate = RealignmentGate(StubVerdictSource(verdict="looks fine to me"))
    decision = gate.review(output="x", direction=DIRECTION)
    assert decision.reason == UNKNOWN_VERDICT
    assert decision.action is Action.PROCEED and decision.checked is False


def test_given_a_fail_closed_gate_when_the_judge_breaks_then_it_blocks():
    gate = RealignmentGate(
        StubVerdictSource(error=TimeoutError("judge down")), policy=GatePolicy(fail_closed=True)
    )
    decision = gate.review(output="x", direction=DIRECTION)
    assert decision.action is Action.BLOCK and decision.reason == SOURCE_ERROR


def test_given_fail_closed_when_drift_can_pause_then_it_still_pauses_not_blocks():
    """Pause preserves the run for a human; fail-closed is about no answer."""
    gate = RealignmentGate(
        StubVerdictSource(Verdict.DRIFTED), policy=GatePolicy(fail_closed=True), can_pause=True
    )
    assert gate.review(output="x", direction=DIRECTION).action is Action.PAUSE


def test_given_no_direction_set_when_reviewing_then_it_is_still_recorded():
    """A crew can start before anyone sets direction; the trace must say so."""
    sink = RecordingSink()
    gate = RealignmentGate(StubVerdictSource(Verdict.ALIGNED), telemetry=sink)

    decision = gate.review(output="x", direction=Direction.empty("default"))

    assert decision.constitution == "default" and decision.version == 0


def test_given_a_blocked_drift_when_serializing_then_the_whole_decision_is_there():
    gate = RealignmentGate(StubVerdictSource(Verdict.DRIFTED))
    assert gate.review(output="x", direction=DIRECTION).to_dict() == {
        "action": "block",
        "verdict": "drifted",
        "checked": True,
        "reason": "drifted",
        "constitution": "eu",
        "version": 4,
    }
