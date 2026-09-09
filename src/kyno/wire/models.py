# SPDX-License-Identifier: MIT
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from kyno.wire.errors import MalformedPrincipleError

_PRINCIPLE_KEYS = ("title", "description")

DIRECTION_MARKER = "[kyno:direction"
COMPACT = "compact"
FULL = "full"
DETAIL_LEVELS = (COMPACT, FULL)


def check_detail(detail: str, what: str = "detail") -> str:
    if detail not in DETAIL_LEVELS:
        raise ValueError(f"unknown {what} '{detail}': choose one of {', '.join(DETAIL_LEVELS)}")
    return detail


def _text(value, field: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise MalformedPrincipleError(
            f"a principle's {field} must be text, got {type(value).__name__}"
        )
    return value.strip()


@dataclass(frozen=True)
class Principle:
    """The operational handle and explanation that make a principle usable."""

    title: str
    description: str = ""

    @classmethod
    def of(cls, value) -> Principle:
        """Accept an existing principle, a title, or a title mapping."""
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            return cls(title=_require_title(_text(value, "title")))
        if isinstance(value, Mapping):
            unknown = sorted(set(value) - set(_PRINCIPLE_KEYS))
            if unknown:
                raise MalformedPrincipleError(
                    f"unknown key(s) on a principle: {', '.join(unknown)} "
                    f"(a principle takes {' and '.join(_PRINCIPLE_KEYS)})"
                )
            return cls(
                title=_require_title(_text(value.get("title"), "title")),
                description=_text(value.get("description"), "description"),
            )
        raise MalformedPrincipleError(
            f"a principle must be a title or a title-and-description, got {type(value).__name__}"
        )

    def to_dict(self, detail: str = FULL) -> dict:
        if check_detail(detail) == COMPACT:
            return {"title": self.title}
        return {"title": self.title, "description": self.description}


def _require_title(title: str) -> str:
    if not title:
        raise MalformedPrincipleError("a principle needs a title")
    return title


def normalize_principles(values: Iterable | None) -> tuple[Principle, ...] | None:
    """Keep None as the signal to carry the previous principles forward."""
    if values is None:
        return None
    if isinstance(values, str | Mapping):
        raise MalformedPrincipleError("principles must be a list of principles, not a single one")
    return tuple(Principle.of(value) for value in values)


class HoldsPrinciples:
    """Normalize principle inputs so readers always see one shape."""

    def __post_init__(self) -> None:
        object.__setattr__(self, "principles", normalize_principles(self.principles) or ())


@dataclass(frozen=True)
class ChangesSince(HoldsPrinciples):
    current_version: int
    changed: bool
    mission: str
    principles: tuple[Principle, ...]
    changed_mission: bool
    changed_principles: bool
    change_notes: tuple[str, ...]
    declaration: str = ""
    delta: tuple[str, ...] = ()

    def to_dict(self, detail: str = FULL) -> dict:
        payload = {
            "current_version": self.current_version,
            "changed": self.changed,
            "mission": self.mission,
        }
        if check_detail(detail) == FULL:
            payload["declaration"] = self.declaration
        payload["principles"] = [principle.to_dict(detail) for principle in self.principles]
        payload["changed_mission"] = self.changed_mission
        payload["changed_principles"] = self.changed_principles
        payload["change_notes"] = list(self.change_notes)
        payload["delta"] = list(self.delta)
        return payload
