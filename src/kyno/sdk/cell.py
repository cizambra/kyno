from __future__ import annotations

import threading
from dataclasses import dataclass

from kyno.models import (
    COMPACT,
    DIRECTION_MARKER,
    FULL,
    ChangesSince,
    HoldsPrinciples,
    Principle,
    check_detail,
)


def is_direction_block(text) -> bool:
    """True only for text that IS a direction block — it starts with the
    marker. Marker text inside other content is data, never an adapter's to
    delete."""
    return isinstance(text, str) and text.startswith(DIRECTION_MARKER)


def refresh(items, block, *, text_of=None, make=None):
    """The rule every adapter follows: exactly one direction block, the
    fresh one, first. `text_of` reads an item's text and `make` builds the
    block's item, so a message-list adapter can inject its own shapes; the
    defaults handle plain strings."""
    text_of = text_of if text_of is not None else lambda item: item
    make = make if make is not None else lambda text: text
    kept = [item for item in items if not is_direction_block(text_of(item))]
    return [make(block), *kept]


def check_context(context: str) -> str:
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
    context: str = COMPACT

    def __post_init__(self) -> None:
        super().__post_init__()
        check_context(self.context)

    @classmethod
    def empty(cls, constitution: str, context: str = COMPACT) -> Direction:
        return cls(constitution=constitution, version=0, mission="", principles=(), context=context)

    @classmethod
    def from_changes(
        cls, changes: ChangesSince, constitution: str, context: str = COMPACT
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
        full = self.context == FULL
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
            "context": self.context,
        }


class DirectionCell:
    """The process-local latest-known direction, one entry per constitution.

    Updates are monotonic: a late reply carrying an older version must not
    undo a newer one, which is what lets the pull and the push race freely.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._held: dict[str, Direction] = {}

    def get(self, constitution: str) -> Direction | None:
        with self._lock:
            return self._held.get(constitution)

    def known_version(self, constitution: str) -> int:
        held = self.get(constitution)
        return held.version if held else 0

    def update(self, direction: Direction) -> Direction:
        with self._lock:
            held = self._held.get(direction.constitution)
            if held is not None and held.version > direction.version:
                return held
            self._held[direction.constitution] = direction
            return direction

    def names(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._held))
