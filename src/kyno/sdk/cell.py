# SPDX-License-Identifier: MIT
from __future__ import annotations

import threading
from dataclasses import dataclass

from kyno.sdk.recording import RecordingReceipt
from kyno.wire.models import (
    DIRECTION_MARKER,
    ChangesSince,
    DetailLevel,
    HoldsPrinciples,
    Principle,
    check_detail,
)


def is_direction_block(text) -> bool:
    """True only for text that starts with the marker. If the marker appears
    inside other content, that content is data, and an adapter must not
    delete it."""
    return isinstance(text, str) and text.startswith(DIRECTION_MARKER)


def refresh(items, block, *, text_of=None, make=None):
    """Keeps exactly one direction block in the list: the fresh one, in
    first place. `text_of` reads the text of an item and `make` builds the
    item for the new block, so an adapter that works with message lists can
    pass its own shapes. The defaults work with plain strings."""
    text_of = text_of if text_of is not None else lambda item: item
    make = make if make is not None else lambda text: text
    kept = [item for item in items if not is_direction_block(text_of(item))]
    return [make(block), *kept]


def check_context(context: str | DetailLevel) -> DetailLevel:
    """The injected block carries the same two levels a read asks Kyno for,
    so an organization has one word for how much context it wants."""
    return check_detail(context, "injection context")


@dataclass(frozen=True)
class Direction(HoldsPrinciples):
    constitution: str
    version: int
    mission: str
    principles: tuple[Principle, ...]
    change_notes: tuple[str, ...] = ()
    delta: tuple[str, ...] = ()
    declaration: str = ""
    context: DetailLevel = DetailLevel.COMPACT

    def __post_init__(self) -> None:
        super().__post_init__()
        object.__setattr__(self, "context", check_context(self.context))

    @classmethod
    def empty(
        cls, constitution: str, context: str | DetailLevel = DetailLevel.COMPACT
    ) -> Direction:
        return cls(constitution=constitution, version=0, mission="", principles=(), context=context)

    @classmethod
    def from_changes(
        cls,
        changes: ChangesSince,
        constitution: str,
        context: str | DetailLevel = DetailLevel.COMPACT,
    ) -> Direction:
        return cls(
            constitution=constitution,
            version=changes.current_version,
            mission=changes.mission,
            principles=changes.principles,
            change_notes=tuple(changes.change_notes),
            delta=tuple(changes.delta),
            declaration=changes.declaration,
            context=context,
        )

    def render(self) -> str:
        """The block injected into a step, and the record of what it served.
        It names the constitution and version so a transcript answers "which
        direction was this agent on" without any other context. What it costs
        is chosen where an integrator binds: compact carries the mission and
        the principle titles, full adds the declaration and the descriptions."""
        header = f"{DIRECTION_MARKER} constitution={self.constitution} version={self.version}]"
        if self.version == 0:
            return f"{header}\nNo direction has been set yet."
        full = self.context is DetailLevel.FULL
        lines = [header, f"Mission: {self.mission}"]
        if full and self.declaration:
            lines.append("Declaration:")
            lines.append(self.declaration)
        if self.principles:
            lines.append("Principles:")
            for principle in self.principles:
                lines.append(f"- {principle.title}")
                if full and principle.description:
                    lines.append(f"  {principle.description}")
        if self.change_notes:
            lines.append("Recent changes:")
            lines.extend(f"- {n}" for n in self.change_notes)
        if self.delta:
            lines.append("What changed:")
            lines.extend(f"- {d}" for d in self.delta)
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "constitution": self.constitution,
            "version": self.version,
            "mission": self.mission,
            "declaration": self.declaration,
            "principles": [p.to_dict() for p in self.principles],
            "change_notes": list(self.change_notes),
            "context": self.context.value,
        }


class DirectionCell:
    """One binder's process-local latest-known direction and receipt.

    Updates are monotonic so overlapping pulls can finish out of order
    without an older response replacing a newer direction.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._held: tuple[Direction, RecordingReceipt | None] | None = None

    def get_with_recording(self) -> tuple[Direction, RecordingReceipt | None] | None:
        """Return the cached direction and its origin receipt as one snapshot."""
        with self._lock:
            return self._held

    def last_seen_version(self) -> int:
        held = self.get_with_recording()
        return held[0].version if held is not None else 0

    def update_with_recording(
        self, direction: Direction, recording: RecordingReceipt | None = None
    ) -> tuple[Direction, RecordingReceipt | None]:
        """Retain direction and receipt together unless a newer version is held."""
        with self._lock:
            held = self._held
            if held is not None and held[0].version > direction.version:
                return held
            snapshot = (direction, recording)
            self._held = snapshot
            return snapshot
