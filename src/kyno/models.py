from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from kyno.wire.errors import UnknownPrincipleError
from kyno.wire.models import (
    FULL,
    HoldsPrinciples,
    Principle,
    check_detail,
)


class AuthorizationType(StrEnum):
    OPERATOR = "operator"
    AUTOMATION = "automation"
    OVERRIDE = "override"


class TokenScope(StrEnum):
    """What a token may do. Read covers every tool except set_direction;
    write covers every tool."""

    READ = "read"
    WRITE = "write"


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
    # Optional and last so existing callers construct a version unchanged. In the payload it
    # sits next to the mission it expands.
    declaration: str = ""
    # None on local and direct writes: those paths ask no approval questions.
    authorized_by: AuthorizationType | None = None
    # The id of the token that authenticated a remote write. Resolved by the
    # server from the request itself, never taken from the client. None on
    # local and stdio writes.
    token_id: int | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.authorized_by is not None:
            object.__setattr__(self, "authorized_by", AuthorizationType(self.authorized_by))

    def principle(self, title: str) -> Principle:
        """The one principle with this exact title. Titles are not unique, so
        the first one wins: the list order is what the operator wrote."""
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
        payload["authorized_by"] = self.authorized_by.value if self.authorized_by else None
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
        # Absent, not empty: an empty list would mean there is no history, when the reason is
        # that this constitution does not publish it.
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
class Token:
    """One kyno_tokens row: the identity that versions reference. There is
    no value and no hash here. The value is shown once at minting, and the
    hash never leaves the store."""

    id: int
    name: str
    scope: TokenScope
    created_at: datetime
    last_used_at: datetime | None = None
    expires_at: datetime | None = None
    revoked_at: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "scope", TokenScope(self.scope))

    def live_at(self, now: datetime) -> bool:
        """Live means the server would accept it: not revoked, not expired.
        Defined once, here, so the CLI and the request check cannot drift."""
        if self.revoked_at is not None:
            return False
        return self.expires_at is None or self.expires_at > now
