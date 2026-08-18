from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any, TypedDict

from langgraph.types import interrupt

from kyno.adapters.core.binder import DirectionBinder
from kyno.adapters.core.cell import COMPACT, Direction
from kyno.adapters.core.gate import Action, RealignmentGate
from kyno.adapters.core.trace import RunTrace


class KynoState(TypedDict, total=False):
    """Inherit this in your graph's state schema. LangGraph only carries the
    keys a schema declares, so without it the direction a node pulls never
    reaches the gate node that must judge against it -- silently.
    """

    kyno_constitution: str
    kyno_version: int
    kyno_mission: str
    kyno_principles: list[dict]
    kyno_context: str
    kyno_direction: str
    kyno_verdict: str
    kyno_checked: bool
    kyno_blocked: bool


def direction_update(direction: Direction) -> dict:
    """Direction travels in graph state so a persisted checkpoint says which
    constitution and version a step served, without any other context."""
    return {
        "kyno_constitution": direction.constitution,
        "kyno_version": direction.version,
        "kyno_mission": direction.mission,
        "kyno_principles": [p.to_dict() for p in direction.principles],
        "kyno_direction": direction.render(),
        "kyno_context": direction.context,
    }


def direction_from_state(state: dict) -> Direction:
    return Direction(
        constitution=state.get("kyno_constitution", "default"),
        version=state.get("kyno_version", 0),
        mission=state.get("kyno_mission", ""),
        principles=state.get("kyno_principles", ()),
        context=state.get("kyno_context", COMPACT),
    )


def direction_node(binder: DirectionBinder, constitution: str = "default") -> Callable:
    """A sentinel node, and the `pre_model_hook` for prebuilt ReAct agents:
    one refresh ahead of a fan-out serves every node downstream."""

    def node(state: dict) -> dict:
        return direction_update(binder.bind(constitution))

    return node


def pull_before(binder: DirectionBinder, constitution: str = "default") -> Callable:
    def decorator(node: Callable) -> Callable:
        @functools.wraps(node)
        def wrapped(state: dict, *args: Any, **kwargs: Any) -> dict:
            direction = binder.bind(constitution)
            update = direction_update(direction)
            result = node({**state, **update}, *args, **kwargs) or {}
            return {**update, **result}

        return wrapped

    return decorator


def gate_node(
    gate: RealignmentGate,
    output_key: str = "output",
    trace: RunTrace | None = None,
) -> Callable:
    """The gate as a node. It judges against the direction already in state --
    binding is direction_node's job. On PAUSE it interrupts; LangGraph re-runs the
    node from its start on resume, so everything before the interrupt here
    is idempotent (a review and a record)."""

    def node(state: dict) -> dict:
        direction = direction_from_state(state)
        output = str(state.get(output_key, ""))
        decision = gate.review(output=output, direction=direction)
        if trace is not None:
            trace.record_step(
                agent=str(state.get("kyno_agent", "graph")),
                goal=str(state.get("kyno_goal", "")),
                output=output,
                direction=direction,
                decision=decision,
            )
        blocked = decision.action is Action.BLOCK
        if decision.action is Action.PAUSE:
            answer = interrupt(
                {
                    "reason": decision.reason,
                    "verdict": decision.verdict.value,
                    "constitution": decision.constitution,
                    "version": decision.version,
                    "output": output,
                }
            )
            blocked = not (isinstance(answer, dict) and answer.get("accept") is True)
        return {
            "kyno_verdict": decision.verdict.value,
            "kyno_checked": decision.checked,
            "kyno_blocked": blocked,
        }

    return node
