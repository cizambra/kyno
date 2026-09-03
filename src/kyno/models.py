from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime

from kyno.errors import MalformedPrincipleError, UnknownPrincipleError

_PRINCIPLE_KEYS = ("title", "description")

# The header adapters stamp on the direction block they inject into model
# calls. Defined beside the document model because the write path refuses
# text carrying it: a constitution field must not be able to forge one.
DIRECTION_MARKER = "[kyno:direction"

# How much of a constitution a caller wants: the handles, or the whole
# document. The long text is what costs, so compact is what defaults.
COMPACT = "compact"
FULL = "full"
DETAIL_LEVELS = (COMPACT, FULL)

# Who stood behind a write. Recorded at write time because it can't be
# reconstructed later: an operator answered the questions, automation ran
# under the checks, or the override flag answered yes to everything.
OPERATOR = "operator"
AUTOMATION = "automation"
OVERRIDE = "override"
AUTHORIZATIONS = (OPERATOR, AUTOMATION, OVERRIDE)

# What a token may do. read covers every tool except set_direction; write
# covers everything.
READ = "read"
WRITE = "write"
SCOPES = (READ, WRITE)


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
    """The short operational handle an agent is steered by, and the paragraph
    that settles an argument about what it means. A principle with no
    description is the whole of what a principle used to be."""

    title: str
    description: str = ""

    @classmethod
    def of(cls, value) -> Principle:
        """Accept a principle in any shape a caller may hold one: the object,
        a plain title, or a {title, description} mapping."""
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
        # At full detail both keys are always there, and "" is the honest
        # answer for a principle nobody has described. A compact read omits
        # the key entirely, because "you did not ask" is a different answer.
        if check_detail(detail) == COMPACT:
            return {"title": self.title}
        return {"title": self.title, "description": self.description}


def _require_title(title: str) -> str:
    if not title:
        raise MalformedPrincipleError("a principle needs a title")
    return title


def normalize_principles(values: Iterable | None) -> tuple[Principle, ...] | None:
    """None survives as None, because that is how callers say "carry the
    previous principles forward" rather than "set an empty list"."""
    if values is None:
        return None
    if isinstance(values, str | Mapping):
        raise MalformedPrincipleError("principles must be a list of principles, not a single one")
    return tuple(Principle.of(v) for v in values)


class HoldsPrinciples:
    """Normalizes on construction, so every caller that has always passed
    plain strings keeps working and every reader sees the same shape."""

    def __post_init__(self) -> None:
        object.__setattr__(self, "principles", normalize_principles(self.principles) or ())


@dataclass(frozen=True)
class ConstitutionVersion(HoldsPrinciples):
    version: int
    mission: str
    principles: tuple[Principle, ...]
    change_note: str
    changed_mission: bool
    changed_principles: bool
    created_at: datetime
    created_by: str | None
    # Optional and last so every existing caller still constructs a version
    # exactly as it did; the payload puts it beside the mission it expands.
    declaration: str = ""
    # None on local and direct writes: that doorway has no questions to record.
    authorized_by: str | None = None

    def principle(self, title: str) -> Principle:
        """The one principle with this exact title. Titles are not unique, so
        the first wins -- an ordered list is what an operator wrote."""
        for principle in self.principles:
            if principle.title == title:
                return principle
        raise UnknownPrincipleError(f"no principle titled '{title}' in version {self.version}")

    def to_dict(self, detail: str = FULL) -> dict:
        payload = {"version": self.version, "mission": self.mission}
        if check_detail(detail) == FULL:
            payload["declaration"] = self.declaration
        payload["principles"] = [p.to_dict(detail) for p in self.principles]
        payload["change_note"] = self.change_note
        payload["changed_mission"] = self.changed_mission
        payload["changed_principles"] = self.changed_principles
        payload["created_at"] = self.created_at.isoformat()
        payload["created_by"] = self.created_by
        payload["authorized_by"] = self.authorized_by
        return payload


@dataclass(frozen=True)
class Publication:
    """Whether a constitution is served publicly, and how much of it."""

    published_at: datetime | None
    history_public: bool

    @property
    def published(self) -> bool:
        return self.published_at is not None


@dataclass(frozen=True)
class PublicVersion:
    version: int
    changed_at: datetime
    change_note: str

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "changed_at": self.changed_at.isoformat(),
            "change_note": self.change_note,
        }


@dataclass(frozen=True)
class PublicConstitution(HoldsPrinciples):
    """What an anonymous visitor is allowed to see of one constitution."""

    name: str
    mission: str
    principles: tuple[Principle, ...]
    version: int
    last_changed_at: datetime
    history: tuple[PublicVersion, ...] | None
    declaration: str = ""

    def to_dict(self) -> dict:
        payload = {
            "constitution": self.name,
            "mission": self.mission,
            "declaration": self.declaration,
            "principles": [p.to_dict() for p in self.principles],
            "version": self.version,
            "last_changed_at": self.last_changed_at.isoformat(),
        }
        # Absent, not empty: an empty list would say there is no history,
        # when the truth is that this constitution does not publish it.
        if self.history is not None:
            payload["history"] = [v.to_dict() for v in self.history]
        return payload

    def to_summary(self) -> dict:
        """The index entry: enough to choose a constitution, not its full text."""
        return {
            "constitution": self.name,
            "mission": self.mission,
            "version": self.version,
            "last_changed_at": self.last_changed_at.isoformat(),
        }


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
    # What actually moved, computed rather than written. A note says why the
    # direction changed; only the delta says which line did.
    delta: tuple[str, ...] = ()

    def to_dict(self, detail: str = FULL) -> dict:
        # The change metadata rides along at every level: it is small, and it
        # is what tells a consumer whether to look any closer.
        payload = {
            "current_version": self.current_version,
            "changed": self.changed,
            "mission": self.mission,
        }
        if check_detail(detail) == FULL:
            payload["declaration"] = self.declaration
        payload["principles"] = [p.to_dict(detail) for p in self.principles]
        payload["changed_mission"] = self.changed_mission
        payload["changed_principles"] = self.changed_principles
        payload["change_notes"] = list(self.change_notes)
        payload["delta"] = list(self.delta)
        return payload


@dataclass(frozen=True)
class Token:
    """One kyno_tokens row: the identity that versions reference. There is
    no value and no hash here -- the value is shown once at minting, and
    the hash never leaves the store."""

    id: int
    name: str
    scope: str
    created_at: datetime
    last_used_at: datetime | None = None
    expires_at: datetime | None = None
    revoked_at: datetime | None = None

    def live_at(self, now: datetime) -> bool:
        """Live means the server would accept it: not revoked, not expired.
        Defined once, here, so the CLI and the request check cannot drift."""
        if self.revoked_at is not None:
            return False
        return self.expires_at is None or self.expires_at > now
