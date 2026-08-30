from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, datetime

from kyno.errors import (
    EmptyChangeError,
    FieldTooLargeError,
    NoFieldChangedError,
    ReservedMarkerError,
    UnknownConstitutionError,
    UnknownVersionError,
    UnpublishableNameError,
    VersionConflictError,
)
from kyno.models import (
    DIRECTION_MARKER,
    ChangesSince,
    ConstitutionVersion,
    Principle,
    Publication,
    PublicConstitution,
    PublicVersion,
    normalize_principles,
)
from kyno.store.base import ConstitutionStore

# The size contract for a constitution, enforced before anything is written.
# Generous for a document a human writes; a hard stop for a payload nobody did.
MAX_MISSION_CHARS = 4_000
MAX_DECLARATION_CHARS = 200_000
MAX_CHANGE_NOTE_CHARS = 2_000
MAX_PRINCIPLES = 100
MAX_PRINCIPLE_TITLE_CHARS = 300
MAX_PRINCIPLE_DESCRIPTION_CHARS = 4_000
MAX_CONSTITUTION_NAME_CHARS = 200

# The public page's contract: it and its .json serve at most this many
# versions, newest first. The full history stays readable to authenticated
# callers over MCP and `kyno export`.
PUBLIC_HISTORY_LIMIT = 100


def _check_text(field: str, value: str | None, cap: int) -> None:
    if value is None:
        return
    if len(value) > cap:
        raise FieldTooLargeError(f"{field} is {len(value)} characters, over the cap of {cap}")
    if DIRECTION_MARKER in value:
        raise ReservedMarkerError(
            f"{field} must not contain '{DIRECTION_MARKER}': that is the header "
            "of the direction block adapters inject into model calls"
        )


def _check_fields(
    *,
    mission: str | None,
    declaration: str | None,
    principles: tuple[Principle, ...] | None,
    change_note: str,
    name: str,
) -> None:
    _check_text("mission", mission, MAX_MISSION_CHARS)
    _check_text("declaration", declaration, MAX_DECLARATION_CHARS)
    _check_text("change_note", change_note, MAX_CHANGE_NOTE_CHARS)
    if len(name) > MAX_CONSTITUTION_NAME_CHARS:
        raise FieldTooLargeError(
            f"the constitution name is {len(name)} characters, "
            f"over the cap of {MAX_CONSTITUTION_NAME_CHARS}"
        )
    if principles is None:
        return
    if len(principles) > MAX_PRINCIPLES:
        raise FieldTooLargeError(f"{len(principles)} principles, over the cap of {MAX_PRINCIPLES}")
    for principle in principles:
        _check_text("a principle title", principle.title, MAX_PRINCIPLE_TITLE_CHARS)
        _check_text(
            "a principle description", principle.description, MAX_PRINCIPLE_DESCRIPTION_CHARS
        )


# A consumer that integrates before anyone has set a direction must not
# crash -- an empty store reads as version 0, nothing set, nothing changed.
# created_at is a fixed epoch, not "now", so repeated empty reads are
# identical and unmistakably a placeholder, not a real write timestamp.
_EMPTY_CONSTITUTION = ConstitutionVersion(
    version=0,
    mission="",
    principles=(),
    change_note="",
    changed_mission=False,
    changed_principles=False,
    created_at=datetime.fromtimestamp(0, tz=UTC),
    created_by=None,
)
_EMPTY_CHANGES = ChangesSince(
    current_version=0,
    changed=False,
    mission="",
    principles=(),
    changed_mission=False,
    changed_principles=False,
    change_notes=(),
)


# Lowercase letters and digits, single hyphens between them: the slug shape
# every publishing platform settled on.
_SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def _delta(before, after) -> tuple[str, ...]:
    """What moved between two versions, in the wording of both.

    Returns nothing when the consumer holds no version: there is no baseline
    to compare against, and the whole direction is already in front of them.
    """
    if before is None or before.version >= after.version:
        return ()
    lines: list[str] = []
    if before.mission != after.mission:
        lines.append(f'The mission was "{before.mission}" and is now "{after.mission}".')
    old = [p.title for p in before.principles]
    new = [p.title for p in after.principles]
    for i, title in enumerate(new):
        if i < len(old) and old[i] != title:
            lines.append(f'Principle {i + 1} was "{old[i]}" and is now "{title}".')
        elif i >= len(old):
            lines.append(f'Principle {i + 1} was added: "{title}".')
    for i in range(len(new), len(old)):
        lines.append(f'Principle {i + 1} was dropped: "{old[i]}".')
    return tuple(lines)


def _slugged(name: str) -> str:
    """The name the caller probably meant. For the error message only -- publishing
    never transforms a name, because the name in the URL has to be the one
    agents pass over MCP."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _check_publishable(name: str) -> None:
    """A published name is a URL and an identity at once: it is what
    /constitutions/<name> serves and what agents pass over MCP. Slugs are what
    survive being pasted into a chat, a slide, or an address bar unmangled, so
    a name that is not one is refused rather than quietly rewritten."""
    if _SLUG.fullmatch(name):
        return
    suggestion = _slugged(name)
    hint = f" like '{suggestion}'" if suggestion else ""
    raise UnpublishableNameError(
        f"'{name}' cannot be published: use a lowercase-and-hyphens name{hint}"
    )


class ControlPlane:
    def __init__(self, store: ConstitutionStore, constitution: str = "default") -> None:
        self._store = store
        self._constitution = constitution
        self._subscribers: list[Callable[[ConstitutionVersion], None]] = []

    def _name(self, constitution: str | None) -> str:
        """Resolve which constitution a call is about.
        The name is per call, never state: naming one here must not redirect
        later calls. Omitting it falls back to the constructor's name, so a
        control plane pinned to one constitution behaves as it always has."""
        return self._constitution if constitution is None else constitution

    def on_change(self, callback: Callable[[ConstitutionVersion], None]) -> None:
        self._subscribers.append(callback)

    def current(self, constitution: str | None = None) -> ConstitutionVersion:
        head = self._store.head(self._name(constitution))
        if head is None:
            return _EMPTY_CONSTITUTION
        return head

    def changes_since(self, known_version: int, constitution: str | None = None) -> ChangesSince:
        name = self._name(constitution)
        head = self._store.head(name)
        if head is None:
            # No HEAD to compare against -- no known_version can be "in the
            # future", so this never raises here (see current()'s docstring
            # note above for the reasoning).
            return _EMPTY_CHANGES
        if known_version > head.version:
            raise UnknownVersionError(f"known_version {known_version} > current {head.version}")
        floor = known_version if known_version > 0 else 0
        newer = self._store.versions_after(name, floor)
        changed = bool(newer)
        return ChangesSince(
            current_version=head.version,
            changed=changed,
            mission=head.mission,
            declaration=head.declaration,
            principles=head.principles,
            changed_mission=any(v.changed_mission for v in newer),
            changed_principles=any(v.changed_principles for v in newer),
            change_notes=tuple(v.change_note for v in newer),
            delta=_delta(self._store.get(name, known_version) if known_version else None, head),
        )

    def publication(self, constitution: str | None = None) -> Publication:
        return self._store.publication(self._name(constitution))

    def publish(
        self, constitution: str | None = None, *, with_history: bool = False
    ) -> Publication:
        """Serve this constitution publicly. History (and the change notes in
        it) stays private unless `with_history` opens it as a separate act."""
        name = self._name(constitution)
        if self._store.head(name) is None:
            raise UnknownConstitutionError(
                f"'{name}' has no direction set, so there is nothing to publish"
            )
        _check_publishable(name)
        already = self._store.publication(name)
        # The stamp records when this constitution went public; turning
        # history on later is not a new publication.
        stamp = already.published_at or datetime.now(UTC)
        self._store.set_publication(name, published_at=stamp, history_public=with_history)
        return self._store.publication(name)

    def unpublish(self, constitution: str | None = None) -> Publication:
        name = self._name(constitution)
        if not self._store.set_publication(name, published_at=None, history_public=False):
            raise UnknownConstitutionError(f"no constitution named '{name}'")
        return self._store.publication(name)

    def public_constitution(self, constitution: str | None = None) -> PublicConstitution | None:
        """The public view of one constitution, or None if it is not published.
        Unknown and unpublished are the same answer on purpose: whether a name
        exists is not something an anonymous caller gets to learn."""
        name = self._name(constitution)
        pub = self._store.publication(name)
        if not pub.published:
            return None
        head = self._store.head(name)
        if head is None:
            return None
        history = None
        if pub.history_public:
            newest_first = reversed(self._store.versions_after(name, 0))
            history = tuple(
                PublicVersion(version=v.version, changed_at=v.created_at, change_note=v.change_note)
                for v in newest_first
            )[:PUBLIC_HISTORY_LIMIT]
        return PublicConstitution(
            name=name,
            mission=head.mission,
            declaration=head.declaration,
            principles=head.principles,
            version=head.version,
            last_changed_at=head.created_at,
            history=history,
        )

    def published_constitutions(self) -> tuple[PublicConstitution, ...]:
        """Every constitution that has been published, by name. Names that are
        not published never appear, so the index cannot disclose a private one."""
        views = (self.public_constitution(name) for name in self._store.published_names())
        return tuple(v for v in views if v is not None)

    def set_direction(
        self,
        *,
        mission: str | None = None,
        declaration: str | None = None,
        principles: tuple[Principle | str, ...] | None = None,
        change_note: str,
        created_by: str | None = None,
        constitution: str | None = None,
    ) -> ConstitutionVersion:
        if not change_note or not change_note.strip():
            raise EmptyChangeError("change_note is required")
        # Before the retry loop: a malformed principle is the caller's
        # mistake, and re-discovering it on every attempt tells nobody more.
        principles = normalize_principles(principles)
        name = self._name(constitution)
        _check_fields(
            mission=mission,
            declaration=declaration,
            principles=principles,
            change_note=change_note,
            name=name,
        )
        head, effective = self._effective(
            name, mission=mission, declaration=declaration, principles=principles
        )
        new_mission, new_declaration, new_principles, changed_mission, changed_principles = (
            effective
        )
        if head is not None and not (
            changed_mission or changed_principles or new_declaration != head.declaration
        ):
            # The two recorded flags stay literally about the fields they
            # name, so a declaration-only edit still appends a version --
            # which is what a polling consumer reads as "changed".
            raise NoFieldChangedError("no field changed")
        next_version = 1 if head is None else head.version + 1
        try:
            version = self._store.append(
                name,
                next_version,
                mission=new_mission,
                declaration=new_declaration,
                principles=new_principles,
                change_note=change_note,
                changed_mission=changed_mission,
                changed_principles=changed_principles,
                created_by=created_by,
            )
        except VersionConflictError:
            # A concurrent writer took this version. Nothing lands: whoever
            # asked decides against the new head, with eyes open.
            raise VersionConflictError(
                f"the head of '{name}' moved while applying; read it again and re-apply"
            ) from None
        for cb in self._subscribers:
            cb(version)
        return version

    def _effective(self, name: str, *, mission, declaration, principles):
        """The head, and what an edit with these fields would make of it:
        (mission, declaration, principles, changed_mission, changed_principles).
        Omitted fields carry forward; on an empty store everything starts."""
        head = self._store.head(name)
        if head is None:
            return head, (
                mission if mission is not None else "",
                declaration if declaration is not None else "",
                principles if principles is not None else (),
                True,
                True,
            )
        new_mission = mission if mission is not None else head.mission
        new_declaration = declaration if declaration is not None else head.declaration
        new_principles = principles if principles is not None else head.principles
        return head, (
            new_mission,
            new_declaration,
            new_principles,
            new_mission != head.mission,
            new_principles != head.principles,
        )

    def preview_edit(
        self,
        *,
        mission: str | None = None,
        declaration: str | None = None,
        principles: tuple[Principle | str, ...] | None = None,
        constitution: str | None = None,
    ) -> tuple[str, ...]:
        """What an apply with these fields would change, as plain sentences.
        Empty means the apply would be refused as no field changed."""
        return self.head_and_delta(
            mission=mission,
            declaration=declaration,
            principles=principles,
            constitution=constitution,
        )[1]

    def head_and_delta(
        self,
        *,
        mission: str | None = None,
        declaration: str | None = None,
        principles: tuple[Principle | str, ...] | None = None,
        constitution: str | None = None,
    ) -> tuple[ConstitutionVersion | None, tuple[str, ...]]:
        """The head and what an apply with these fields would change, from
        one read of the store, so the version and the delta can never
        describe two different moments. The head is None on an empty store."""
        principles = normalize_principles(principles)
        name = self._name(constitution)
        head, effective = self._effective(
            name, mission=mission, declaration=declaration, principles=principles
        )
        new_mission, new_declaration, new_principles, changed_mission, changed_principles = (
            effective
        )
        if head is None:
            return None, (f"Creates '{name}' at version 1.",)
        after = ConstitutionVersion(
            version=head.version + 1,
            mission=new_mission,
            declaration=new_declaration,
            principles=new_principles,
            change_note="",
            changed_mission=changed_mission,
            changed_principles=changed_principles,
            created_at=head.created_at,
            created_by=None,
        )
        lines = list(_delta(head, after))
        if new_declaration != head.declaration:
            lines.append("The declaration changed.")
        return head, tuple(lines)
