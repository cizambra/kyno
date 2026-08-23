from __future__ import annotations

from typing import Any

from kyno.sdk.binder import DirectionBinder
from kyno.sdk.cell import Direction, refresh
from kyno.sdk.gate import RealignmentGate
from kyno.sdk.trace import RunTrace


class TaskBlockedByKyno(RuntimeError):
    """Raised from task_callback when the gate rules DRIFTED.

    task_callback has no return-based block signal the way before_llm_call /
    after_llm_call do, so raising is the only lever at this granularity --
    the exception propagates through Crew.kickoff() like any other.
    """

    def __init__(self, reason: str, *, direction: Direction) -> None:
        super().__init__(
            f"kyno gate blocked task: {reason} "
            f"(constitution={direction.constitution}, version={direction.version})"
        )
        self.reason = reason
        self.direction = direction


class CrewAiKyno:
    """Direction injection (before_llm_call) and the gate (task_callback) for CrewAI.

    Gating is per finished task, not per LLM call: a task can involve
    several model calls, and once a real judge is attached, gating each one
    multiplies its cost by every call instead of charging it once.
    """

    def __init__(
        self,
        binder: DirectionBinder,
        gate: RealignmentGate | None = None,
        constitution: str = "default",
        trace: RunTrace | None = None,
    ) -> None:
        self._binder = binder
        # No gate unless one is handed in. Kyno carries direction; checking the
        # work against it needs a judge Kyno does not ship, so a default gate
        # would only ever answer "unchecked".
        self.gate = gate
        self.constitution = constitution
        self.trace = trace

    def before_llm_call(self, ctx: Any) -> None:
        direction = self._binder.bind(self.constitution)
        messages = getattr(ctx, "messages", None)
        if messages is None:
            messages = ctx.messages = []
        # CrewAI's executor keeps a reference to this list, so rebinding it
        # would silently detach the hook from the call it is editing.
        messages[:] = refresh(
            messages,
            direction.render(),
            text_of=_system_content,
            make=lambda block: {"role": "system", "content": block},
        )

    def task_callback(self, task_output: Any) -> None:
        direction = self._binder.cell.get(self.constitution) or Direction.empty(self.constitution)
        output = _output_text(task_output)
        decision = self.gate.review(output=output, direction=direction) if self.gate else None
        if self.trace is not None:
            self.trace.record_step(
                agent=_name_of(getattr(task_output, "agent", "")),
                goal=str(getattr(task_output, "description", "")),
                output=output,
                direction=direction,
                decision=decision,
            )
        if decision is not None and decision.halts(can_pause=False):
            # CrewAI cannot resume a paused task, so a pause behaves like a
            # block here.
            raise TaskBlockedByKyno(decision.reason, direction=direction)

    def step_callback(self, step_output: Any) -> None:
        if self.trace is None:
            return
        direction = self._binder.cell.get(self.constitution) or Direction.empty(self.constitution)
        self.trace.record_step(
            agent=_name_of(getattr(step_output, "agent", "")),
            goal=_name_of(getattr(step_output, "task", "")),
            output=str(getattr(step_output, "output", step_output)),
            direction=direction,
        )

    def register(self) -> None:
        """Only before_llm_call is globally registrable; the callbacks below
        are Crew constructor parameters. The decorator form stamps an
        attribute on what it is handed and so rejects a bound method."""
        from crewai.hooks import register_before_llm_call_hook

        register_before_llm_call_hook(self.before_llm_call)

    def unregister(self) -> bool:
        from crewai.hooks import unregister_before_llm_call_hook

        return unregister_before_llm_call_hook(self.before_llm_call)


def _system_content(message: Any) -> str:
    # Only a system message can be the block this adapter injected; marker
    # text on any other role is data (a tool result echoed into the
    # transcript, a user paste) and is never the adapter's to delete.
    if not isinstance(message, dict) or message.get("role") != "system":
        return ""
    content = message.get("content", "")
    return content if isinstance(content, str) else ""


def _output_text(ctx: Any) -> str:
    for attribute in ("raw", "response", "payload", "output"):
        value = getattr(ctx, attribute, None)
        if value:
            return str(value)
    return ""


def _name_of(value: Any) -> str:
    for attribute in ("role", "name", "description"):
        found = getattr(value, attribute, None)
        if found:
            return str(found)
    return str(value)
