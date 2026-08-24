# SPDX-License-Identifier: MIT
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from datetime import UTC, datetime

from kyno.models import HoldsPrinciples, Principle
from kyno.sdk.cell import Direction
from kyno.sdk.gate import GateDecision, Verdict

# The per-step record shape offered to drift analysis. Named as a tuple so
# renaming a field breaks a test in this repo rather than a consumer
# somewhere else.
SERVES_DIRECTION_FIELDS = (
    "step_id",
    "agent",
    "goal",
    "output",
    "constitution",
    "version",
    "mission",
    "principles",
    "verdict",
    "checked",
    "occurred_at",
)

TASK = "task"
DELEGATION = "delegation"
SUBGRAPH = "subgraph"

# The trace-level shape offered to decomposition analysis: the original
# goal, every step, and the edges that say what was split into what. Without
# the edges a split is invisible and no analysis can judge it.
DECOMPOSITION_COHERES_FIELDS = ("run_id", "goal", "steps", "edges")


@dataclass(frozen=True)
class DecompositionEdge:
    parent_id: str
    child_id: str
    kind: str

    def to_dict(self) -> dict:
        return {"parent_id": self.parent_id, "child_id": self.child_id, "kind": self.kind}


@dataclass(frozen=True)
class StepRecord(HoldsPrinciples):
    step_id: str
    agent: str
    goal: str
    output: str
    constitution: str
    version: int
    mission: str
    principles: tuple[Principle, ...]
    verdict: str
    checked: bool
    occurred_at: datetime

    def to_dict(self) -> dict:
        return {
            "step_id": self.step_id,
            "agent": self.agent,
            "goal": self.goal,
            "output": self.output,
            "constitution": self.constitution,
            "version": self.version,
            "mission": self.mission,
            "principles": [p.to_dict() for p in self.principles],
            "verdict": self.verdict,
            "checked": self.checked,
            "occurred_at": self.occurred_at.isoformat(),
        }


@dataclass
class RunTrace:
    """What the adapters make observable about a run: every step, the
    direction it was bound to, and how the gate ruled. It records; it never
    judges -- judging belongs to the drift benchmark, and keeping it out is
    what keeps this importable with no model installed."""

    run_id: str
    goal: str = ""
    steps: tuple[StepRecord, ...] = ()
    edges: tuple[DecompositionEdge, ...] = ()
    _ids: itertools.count = field(default_factory=lambda: itertools.count(1), repr=False)

    def record_step(
        self,
        *,
        agent: str,
        goal: str,
        output: str,
        direction: Direction,
        decision: GateDecision | None = None,
        step_id: str | None = None,
    ) -> StepRecord:
        record = StepRecord(
            step_id=step_id or f"{self.run_id}-s{next(self._ids)}",
            agent=agent,
            goal=goal,
            output=output,
            constitution=direction.constitution,
            version=direction.version,
            mission=direction.mission,
            principles=direction.principles,
            verdict=(decision.verdict if decision else Verdict.UNKNOWN).value,
            checked=bool(decision and decision.checked),
            occurred_at=datetime.now(tz=UTC),
        )
        self.steps = (*self.steps, record)
        return record

    def record_decomposition(self, parent_id: str, child_id: str, kind: str) -> DecompositionEdge:
        edge = DecompositionEdge(parent_id=parent_id, child_id=child_id, kind=kind)
        self.edges = (*self.edges, edge)
        return edge

    def children(self, step_id: str) -> tuple[StepRecord, ...]:
        by_id = {s.step_id: s for s in self.steps}
        if step_id not in by_id:
            raise KeyError(step_id)
        child_ids = [e.child_id for e in self.edges if e.parent_id == step_id]
        return tuple(by_id[c] for c in child_ids if c in by_id)

    def roots(self) -> tuple[StepRecord, ...]:
        split_into = {e.child_id for e in self.edges}
        return tuple(s for s in self.steps if s.step_id not in split_into)

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "goal": self.goal,
            "steps": [s.to_dict() for s in self.steps],
            "edges": [e.to_dict() for e in self.edges],
        }
