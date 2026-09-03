from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import Engine, create_engine, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool

from kyno.errors import ConfigError, CorruptStateError, VersionConflictError
from kyno.models import (
    ConstitutionVersion,
    Principle,
    Publication,
    Token,
    normalize_principles,
)
from kyno.store.schema import build_metadata


def _encode_principles(principles) -> str:
    normalized = normalize_principles(principles) or ()
    return json.dumps([p.to_dict() if p.description else p.title for p in normalized])


# missing driver module -> the pip extra that ships it
_DRIVER_EXTRAS = {"psycopg": "postgres", "pymysql": "mysql"}


class SqlConstitutionStore:
    def __init__(
        self, engine: Engine | None = None, *, url: str | None = None, prefix: str = "kyno_"
    ) -> None:
        if (engine is None) == (url is None):
            raise ValueError("provide exactly one of `engine` or `url`")
        if engine is None:
            kwargs = {}
            if url and url.startswith("sqlite"):
                # An in-memory SQLite database lives inside a single
                # connection — open a second connection and you get a
                # different, empty database. StaticPool reuses that one
                # connection, and the same-thread guard must be off too.
                if url in ("sqlite://", "sqlite:///:memory:") or url.endswith(":memory:"):
                    kwargs = {
                        "connect_args": {"check_same_thread": False},
                        "poolclass": StaticPool,
                    }
                else:
                    # A file-backed SQLite database is shared through the
                    # file itself, so it only needs the thread guard off.
                    kwargs = {"connect_args": {"check_same_thread": False}}
            try:
                self.engine = create_engine(url, **kwargs)
            except ModuleNotFoundError as exc:
                # The exception already names the missing driver; the map
                # turns it into the extra that installs it.
                extra = _DRIVER_EXTRAS.get(exc.name)
                hint = (
                    f"install it with: pip install kyno[{extra}]"
                    if extra
                    else f"install the '{exc.name}' package"
                )
                raise ConfigError(
                    f"the database at this URL needs a driver that is not installed; {hint}"
                ) from None
        else:
            self.engine = engine
        self.metadata, self._constitutions, self._versions, self._tokens = build_metadata(prefix)

    def create_all(self) -> None:
        self.metadata.create_all(self.engine)

    def _row_to_version(self, row) -> ConstitutionVersion:
        created_at = row.created_at
        # SQLite stores our timestamps but hands them back without the
        # timezone attached. Everything this store writes is UTC (see
        # append()), so put the UTC label back on when reading.
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        return ConstitutionVersion(
            version=row.version,
            mission=row.mission,
            declaration=row.declaration or "",
            principles=json.loads(row.principles),
            change_note=row.change_note,
            changed_mission=bool(row.changed_mission),
            changed_principles=bool(row.changed_principles),
            created_at=created_at,
            created_by=row.created_by,
            authorized_by=row.authorized_by,
        )

    def _constitution_id(self, conn, constitution: str) -> int | None:
        row = conn.execute(
            select(self._constitutions.c.id).where(self._constitutions.c.name == constitution)
        ).first()
        return row.id if row else None

    def head(self, constitution: str) -> ConstitutionVersion | None:
        with self.engine.connect() as conn:
            cur = conn.execute(
                select(self._constitutions.c.id, self._constitutions.c.current_version).where(
                    self._constitutions.c.name == constitution
                )
            ).first()
            if cur is None:
                return None
            row = conn.execute(
                select(self._versions)
                .where(self._versions.c.constitution_id == cur.id)
                .where(self._versions.c.version == cur.current_version)
            ).first()
            if row is None:
                raise CorruptStateError(
                    f"constitution '{constitution}' has HEAD pointing at version "
                    f"{cur.current_version}, but that version row is missing"
                )
            return self._row_to_version(row)

    def get(self, constitution: str, version: int) -> ConstitutionVersion | None:
        with self.engine.connect() as conn:
            cid = self._constitution_id(conn, constitution)
            if cid is None:
                return None
            row = conn.execute(
                select(self._versions)
                .where(self._versions.c.constitution_id == cid)
                .where(self._versions.c.version == version)
            ).first()
            return self._row_to_version(row) if row else None

    def versions_after(self, constitution: str, known_version: int) -> list[ConstitutionVersion]:
        with self.engine.connect() as conn:
            cid = self._constitution_id(conn, constitution)
            if cid is None:
                return []
            rows = conn.execute(
                select(self._versions)
                .where(self._versions.c.constitution_id == cid)
                .where(self._versions.c.version > known_version)
                .order_by(self._versions.c.version.asc())
            ).all()
            return [self._row_to_version(r) for r in rows]

    def export_versions(
        self,
        constitution: str = "default",
        *,
        from_version: int | None = None,
        to_version: int | None = None,
    ) -> list[dict]:
        """Serialize a version range to plain dicts, ascending by version.
        Bounds are inclusive; an omitted bound means "from the beginning" or
        "to head". An empty store or range returns an empty list rather than
        raising, consistent with the read-never-fails contract elsewhere."""
        with self.engine.connect() as conn:
            cid = self._constitution_id(conn, constitution)
            if cid is None:
                return []
            query = select(self._versions).where(self._versions.c.constitution_id == cid)
            if from_version is not None:
                query = query.where(self._versions.c.version >= from_version)
            if to_version is not None:
                query = query.where(self._versions.c.version <= to_version)
            query = query.order_by(self._versions.c.version.asc())
            rows = conn.execute(query).all()
            versions = [self._row_to_version(r) for r in rows]
        return [
            {
                "version": v.version,
                "mission": v.mission,
                "declaration": v.declaration,
                "principles": [p.to_dict() for p in v.principles],
                "change_note": v.change_note,
                "created_by": v.created_by,
                "authorized_by": v.authorized_by,
                "created_at": v.created_at.isoformat(),
            }
            for v in versions
        ]

    def publication(self, constitution: str) -> Publication:
        with self.engine.connect() as conn:
            row = conn.execute(
                select(
                    self._constitutions.c.published_at, self._constitutions.c.history_public
                ).where(self._constitutions.c.name == constitution)
            ).first()
        if row is None:
            return Publication(published_at=None, history_public=False)
        published_at = row.published_at
        # SQLite hands timestamps back without the timezone we wrote them with.
        if published_at is not None and published_at.tzinfo is None:
            published_at = published_at.replace(tzinfo=UTC)
        return Publication(published_at=published_at, history_public=bool(row.history_public))

    def published_names(self) -> list[str]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(self._constitutions.c.name)
                .where(self._constitutions.c.published_at.is_not(None))
                .order_by(self._constitutions.c.name.asc())
            ).all()
        return [row.name for row in rows]

    def set_publication(
        self, constitution: str, *, published_at: datetime | None, history_public: bool
    ) -> bool:
        """Record (or clear) publication. False means the name does not exist,
        which callers turn into an error rather than a silent success -- a typo
        must not report that something was published."""
        with self.engine.begin() as conn:
            result = conn.execute(
                update(self._constitutions)
                .where(self._constitutions.c.name == constitution)
                .values(published_at=published_at, history_public=history_public)
            )
            return result.rowcount > 0

    def append(
        self,
        constitution: str,
        version: int,
        *,
        mission: str,
        principles: tuple[Principle | str, ...],
        change_note: str,
        declaration: str = "",
        changed_mission: bool,
        changed_principles: bool,
        created_by: str | None,
        authorized_by: str | None = None,
    ) -> ConstitutionVersion:
        now = datetime.now(UTC)
        try:
            with self.engine.begin() as conn:
                cid = self._constitution_id(conn, constitution)
                if cid is None:
                    cid = conn.execute(
                        insert(self._constitutions).values(
                            name=constitution,
                            current_version=version,
                            created_at=now,
                        )
                    ).inserted_primary_key[0]
                else:
                    conn.execute(
                        update(self._constitutions)
                        .where(self._constitutions.c.id == cid)
                        .values(current_version=version)
                    )
                conn.execute(
                    insert(self._versions).values(
                        constitution_id=cid,
                        version=version,
                        mission=mission,
                        declaration=declaration,
                        principles=_encode_principles(principles),
                        change_note=change_note,
                        changed_mission=changed_mission,
                        changed_principles=changed_principles,
                        created_at=now,
                        created_by=created_by,
                        authorized_by=authorized_by,
                    )
                )
        except IntegrityError as exc:
            raise VersionConflictError(
                f"version {version} of '{constitution}' already exists"
            ) from exc
        return ConstitutionVersion(
            version=version,
            mission=mission,
            declaration=declaration,
            principles=principles,
            change_note=change_note,
            changed_mission=changed_mission,
            changed_principles=changed_principles,
            created_at=now,
            created_by=created_by,
            authorized_by=authorized_by,
        )

    def _row_to_token(self, row) -> Token:
        def utc(dt):
            # The same SQLite restamp as _row_to_version: this store only
            # ever writes UTC.
            if dt is not None and dt.tzinfo is None:
                return dt.replace(tzinfo=UTC)
            return dt

        return Token(
            id=row.id,
            name=row.name,
            scope=row.scope,
            created_at=utc(row.created_at),
            last_used_at=utc(row.last_used_at),
            expires_at=utc(row.expires_at),
            revoked_at=utc(row.revoked_at),
        )

    def add_token(
        self, name: str, scope: str, *, token_hash: str, expires_at: datetime | None = None
    ) -> Token:
        """Insert one token row. The caller holds the value; only its hash
        arrives here."""
        now = datetime.now(UTC)
        with self.engine.begin() as conn:
            tid = conn.execute(
                insert(self._tokens).values(
                    name=name,
                    scope=scope,
                    token_hash=token_hash,
                    created_at=now,
                    expires_at=expires_at,
                )
            ).inserted_primary_key[0]
        return Token(id=tid, name=name, scope=scope, created_at=now, expires_at=expires_at)

    def token(self, token_id: int) -> Token | None:
        with self.engine.connect() as conn:
            row = conn.execute(select(self._tokens).where(self._tokens.c.id == token_id)).first()
        return self._row_to_token(row) if row else None

    def tokens(self) -> list[Token]:
        """Every token row, ascending id. Liveness is the caller's filter:
        rows are never deleted, so all really is all."""
        with self.engine.connect() as conn:
            rows = conn.execute(select(self._tokens).order_by(self._tokens.c.id.asc())).all()
        return [self._row_to_token(r) for r in rows]

    def revoke_token(self, token_id: int) -> bool:
        """Set revoked_at. False means nothing changed: no such id, or
        already revoked -- an existing revocation stamp is history, and
        history does not move."""
        with self.engine.begin() as conn:
            result = conn.execute(
                update(self._tokens)
                .where(self._tokens.c.id == token_id)
                .where(self._tokens.c.revoked_at.is_(None))
                .values(revoked_at=datetime.now(UTC))
            )
        return result.rowcount > 0
