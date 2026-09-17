"""Core operations shared by MCP request handlers."""

from __future__ import annotations

from sqlalchemy.exc import SQLAlchemyError

from kyno.mcp.tools import PRINCIPLES_DETAIL_LEVELS, TITLES
from kyno.models import Token
from kyno.service import ControlPlane
from kyno.wire.errors import CoherenceError
from kyno.wire.models import DetailLevel, check_detail


def check_principles_detail(detail: str) -> str:
    if detail not in PRINCIPLES_DETAIL_LEVELS:
        raise ValueError(
            f"unknown detail '{detail}': choose one of {', '.join(PRINCIPLES_DETAIL_LEVELS)}"
        )
    return detail


def _guard(fn):
    try:
        return fn()
    except CoherenceError as exc:
        raise ValueError(str(exc)) from exc


def _require(arguments: dict, key: str) -> None:
    if key not in arguments:
        raise ValueError(f"missing required argument: {key}")


def _delivery_query(cp: ControlPlane, read) -> dict:
    if cp.delivery_record_store is None:
        raise ValueError("delivery history is not configured on this Core instance")
    try:
        return read(cp.delivery_record_store)
    except SQLAlchemyError:
        raise ValueError("delivery history is unavailable") from None


# Reads default to compact. The declaration and the descriptions are the long text, and an agent
# that pulls before every step would pay for them every time. One argument asks for them.
def handle_get_constitution(
    cp: ControlPlane,
    constitution: str | None = None,
    detail: str | DetailLevel = DetailLevel.COMPACT,
    *,
    version: int | None = None,
) -> dict:
    check_detail(detail)
    return _guard(lambda: cp.get_constitution(constitution, version=version).to_dict(detail))


def handle_get_changes_since(
    cp: ControlPlane,
    known_version: int,
    constitution: str | None = None,
    detail: str | DetailLevel = DetailLevel.COMPACT,
) -> dict:
    check_detail(detail)
    return _guard(lambda: cp.changes_since(known_version, constitution).to_dict(detail))


# The targeted reads: after pulling the titles, fetch the one piece that matters instead of the
# whole document again. Each answers with the version it came from, so answers can be combined:
# two answers on the same version describe the same document.
def handle_export_versions(
    cp: ControlPlane,
    constitution: str | None = None,
    from_version: int | None = None,
    to_version: int | None = None,
) -> list[dict]:
    return _guard(
        lambda: cp.export_versions(constitution, from_version=from_version, to_version=to_version)
    )


def handle_get_mission(cp: ControlPlane, constitution: str | None = None) -> dict:
    def read() -> dict:
        head = cp.current(constitution)
        return {"version": head.version, "mission": head.mission}

    return _guard(read)


def handle_get_declaration(cp: ControlPlane, constitution: str | None = None) -> dict:
    def read() -> dict:
        head = cp.current(constitution)
        return {"version": head.version, "declaration": head.declaration}

    return _guard(read)


def handle_get_principles(
    cp: ControlPlane, constitution: str | None = None, detail: str = TITLES
) -> dict:
    check_principles_detail(detail)

    def read() -> dict:
        head = cp.current(constitution)
        shape = DetailLevel.COMPACT if detail == TITLES else DetailLevel.FULL
        return {
            "version": head.version,
            "principles": [p.to_dict(shape) for p in head.principles],
        }

    return _guard(read)


def handle_get_principle(cp: ControlPlane, title: str, constitution: str | None = None) -> dict:
    def read() -> dict:
        head = cp.current(constitution)
        return {**head.principle(title).to_dict(), "version": head.version}

    return _guard(read)


def handle_whoami(token: Token | None) -> dict:
    """What the server knows about the credential behind the current
    request: its id, name and scope, as `kyno whoami --remote` shows them.

    `token` is the row the endpoint authenticated, resolved from the
    request's bearer header. It is None where no bearer token exists:
    stdio, in-process sessions, and a server running with allow_insecure.
    Those answer with nulls in every field."""
    if token is None:
        return {"id": None, "name": None, "scope": None}
    return {"id": token.id, "name": token.name, "scope": token.scope.value}


def handle_set_direction(
    cp: ControlPlane,
    *,
    mission,
    principles,
    change_note,
    created_by,
    declaration=None,
    constitution: str | None = None,
    expected_version: int | None = None,
    authorized_by: str | None = None,
    token_id: int | None = None,
) -> dict:
    return _guard(
        lambda: cp.set_direction(
            mission=mission,
            declaration=declaration,
            principles=tuple(principles) if principles is not None else None,
            change_note=change_note,
            created_by=created_by,
            constitution=constitution,
            expected_version=expected_version,
            authorized_by=authorized_by,
            token_id=token_id,
        ).to_dict()
    )
