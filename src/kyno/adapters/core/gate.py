from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from kyno.adapters.core.cell import Direction
from kyno.adapters.core.policy import (
    DRIFT_BLOCKED,
    DRIFT_PAUSED,
    PAUSE_UNSUPPORTED,
    UNCHECKED,
    GatePolicy,
    LogSink,
    TelemetryEvent,
    TelemetrySink,
)
from kyno.models import Principle

NO_SOURCE = "no_source"
SOURCE_ERROR = "source_error"
DRIFTED_REASON = "drifted"
ALIGNED_REASON = "aligned"
UNKNOWN_VERDICT = "unknown_verdict"


class Verdict(Enum):
    ALIGNED = "aligned"
    DRIFTED = "drifted"
    UNKNOWN = "unknown"


class VerdictSource(Protocol):
    def assess(
        self,
        *,
        output: str,
        mission: str,
        principles: tuple[Principle, ...],
        change_notes: tuple[str, ...],
    ) -> Verdict: ...


class Action(Enum):
    PROCEED = "proceed"
    BLOCK = "block"
    PAUSE = "pause"


@dataclass(frozen=True)
class GateDecision:
    action: Action
    verdict: Verdict
    checked: bool
    reason: str
    constitution: str
    version: int

    def to_dict(self) -> dict:
        return {
            "action": self.action.value,
            "verdict": self.verdict.value,
            "checked": self.checked,
            "reason": self.reason,
            "constitution": self.constitution,
            "version": self.version,
        }


class RealignmentGate:
    """Deliberately model-free: it asks a VerdictSource and acts
    on the answer. When no answer is available the work proceeds MARKED
    unchecked -- an outage of ours must not freeze the host system, and
    unchecked-but-marked keeps the evidence a block would have destroyed."""

    def __init__(
        self,
        source: VerdictSource | None = None,
        policy: GatePolicy | None = None,
        telemetry: TelemetrySink | None = None,
        can_pause: bool = False,
    ) -> None:
        self._source = source
        self._policy = policy or GatePolicy()
        self._telemetry = telemetry or LogSink()
        self._can_pause = can_pause

    def review(self, *, output: str, direction: Direction) -> GateDecision:
        verdict, reason = self._assess(output, direction)
        if verdict is Verdict.ALIGNED:
            return self._decision(Action.PROCEED, verdict, True, ALIGNED_REASON, direction)
        if verdict is Verdict.DRIFTED:
            return self._on_drift(direction)
        return self._on_unknown(reason, direction)

    def _assess(self, output: str, direction: Direction) -> tuple[Verdict, str]:
        if self._source is None:
            return Verdict.UNKNOWN, NO_SOURCE
        try:
            verdict = self._source.assess(
                output=output,
                mission=direction.mission,
                principles=direction.principles,
                change_notes=direction.change_notes,
            )
        except Exception as exc:
            return Verdict.UNKNOWN, f"{SOURCE_ERROR}:{exc}"
        reasons = {Verdict.ALIGNED: ALIGNED_REASON, Verdict.DRIFTED: DRIFTED_REASON}
        return verdict, reasons.get(verdict, UNKNOWN_VERDICT)

    def _on_drift(self, direction: Direction) -> GateDecision:
        if self._can_pause:
            self._emit(DRIFT_PAUSED, direction, DRIFTED_REASON)
            return self._decision(Action.PAUSE, Verdict.DRIFTED, True, DRIFTED_REASON, direction)
        self._emit(DRIFT_BLOCKED, direction, DRIFTED_REASON)
        self._emit(PAUSE_UNSUPPORTED, direction, "framework cannot pause; blocked instead")
        return self._decision(Action.BLOCK, Verdict.DRIFTED, True, DRIFTED_REASON, direction)

    def _on_unknown(self, reason: str, direction: Direction) -> GateDecision:
        detail, _, message = reason.partition(":")
        self._emit(UNCHECKED, direction, message or detail)
        action = Action.BLOCK if self._policy.fail_closed else Action.PROCEED
        return self._decision(action, Verdict.UNKNOWN, False, detail, direction)

    def _decision(
        self, action: Action, verdict: Verdict, checked: bool, reason: str, direction: Direction
    ) -> GateDecision:
        return GateDecision(
            action=action,
            verdict=verdict,
            checked=checked,
            reason=reason,
            constitution=direction.constitution,
            version=direction.version,
        )

    def _emit(self, kind: str, direction: Direction, detail: str) -> None:
        self._telemetry.emit(
            TelemetryEvent(
                kind=kind,
                constitution=direction.constitution,
                version=direction.version,
                detail=detail,
            )
        )
