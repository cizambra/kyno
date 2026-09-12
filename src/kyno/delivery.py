from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import JsonValue, TypeAdapter, ValidationError
from sqlalchemy import insert, select

from kyno.store.schema import build_metadata
from kyno.wire.delivery import RecordingStatus, recording_result

MAX_METADATA_BYTES = 16_384
MAX_SESSION_CHARS = 255
_metadata_adapter = TypeAdapter(dict[str, JsonValue])
_log = logging.getLogger("kyno.delivery")


class RecordingPolicy(StrEnum):
    NEVER = "never"
    ALWAYS = "always"


def recording_failure(exc: Exception) -> dict:
    _log.warning("delivery_recording_failed", extra={"error_type": type(exc).__name__})
    return recording_result(RecordingStatus.FAILED)


def delivery_context(arguments: dict) -> dict:
    session_id = arguments.get("session_id")
    if session_id is not None and (
        not isinstance(session_id, str) or len(session_id) > MAX_SESSION_CHARS
    ):
        raise ValueError(f"session_id must be a string of at most {MAX_SESSION_CHARS} characters")
    try:
        metadata = _metadata_adapter.validate_python(arguments.get("metadata", {}), strict=True)
        encoded = json.dumps(metadata, allow_nan=False)
    except (ValidationError, TypeError, ValueError, RecursionError):
        raise ValueError("metadata must be a JSON object with finite numbers") from None
    if len(encoded.encode("utf-8")) > MAX_METADATA_BYTES:
        raise ValueError(f"metadata exceeds {MAX_METADATA_BYTES} encoded bytes")
    return {"session_id": session_id, "metadata": json.loads(encoded)}


def _timestamp(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError("history timestamps must be ISO timestamps with a timezone") from None
    if parsed.tzinfo is None:
        raise ValueError("history timestamps must include a timezone")
    return parsed.astimezone(UTC).isoformat(timespec="microseconds")


class DeliveryHistory:
    def __init__(self, engine, *, policy=RecordingPolicy.NEVER, prefix: str = "kyno_"):
        self._engine = engine
        self.policy = RecordingPolicy(policy)
        metadata, self._constitutions, *_ = build_metadata(prefix)
        self._table = metadata.tables[f"{prefix}deliveries"]

    def record(
        self,
        direction: dict,
        *,
        operation: str,
        constitution: str,
        arguments: dict,
        context: dict,
        requester: dict | None = None,
    ) -> dict:
        """Return persistence status without making a recording failure fail the read."""
        if self.policy is RecordingPolicy.NEVER:
            return recording_result(RecordingStatus.DISABLED)
        try:
            identifier = str(uuid4())
            self._insert(
                delivery_id=identifier,
                recorded_at=datetime.now(UTC).isoformat(timespec="microseconds"),
                requested_constitution=constitution,
                served_version=direction[
                    "current_version" if operation == "get_changes_since" else "version"
                ],
                operation=operation,
                known_version=arguments.get("known_version"),
                detail_level=arguments.get("detail"),
                selection=json.dumps(
                    {key: arguments[key] for key in ("title",) if key in arguments}
                ),
                direction=json.dumps(direction, allow_nan=False),
                requester=json.dumps(requester),
                session_id=context["session_id"],
                metadata=json.dumps(context["metadata"], allow_nan=False),
            )
        except Exception as exc:
            return recording_failure(exc)
        return recording_result(RecordingStatus.RECORDED, identifier)

    def _insert(self, **values) -> None:
        with self._engine.begin() as connection:
            constitution_id = (
                connection.scalar(
                    select(self._constitutions.c.id).where(
                        self._constitutions.c.name == values["requested_constitution"]
                    )
                )
                if values["served_version"]
                else None
            )
            connection.execute(
                insert(self._table).values(constitution_id=constitution_id, **values)
            )

    def _decode(self, row) -> dict:
        record = dict(row)
        record.pop("sequence")
        for key in ("direction", "requester", "metadata", "selection"):
            record[key] = json.loads(record[key])
        return record

    def get(self, delivery_id: str) -> dict:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(self._table).where(self._table.c.delivery_id == delivery_id)
                )
                .mappings()
                .first()
            )
        if row is None:
            raise ValueError("delivery record not found")
        return self._decode(row)

    def list(
        self,
        *,
        session_id: str | None = None,
        constitution: str | None = None,
        since: str | None = None,
        until: str | None = None,
        after: int = 0,
        limit: int = 50,
    ) -> dict:
        """Return an oldest-first page and the cursor for the next page, if present."""
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("limit must be an integer from 1 to 100")
        if type(after) is not int or after < 0:
            raise ValueError("after must be a nonnegative integer")
        since, until = _timestamp(since), _timestamp(until)
        if since and until and since > until:
            raise ValueError("since must not be later than until")
        query = select(self._table).where(self._table.c.sequence > after)
        for column, value in (
            (self._table.c.session_id, session_id),
            (self._table.c.requested_constitution, constitution),
        ):
            if value is not None:
                query = query.where(column == value)
        if since:
            query = query.where(self._table.c.recorded_at >= since)
        if until:
            query = query.where(self._table.c.recorded_at <= until)
        with self._engine.connect() as connection:
            rows = (
                connection.execute(query.order_by(self._table.c.sequence).limit(limit + 1))
                .mappings()
                .all()
            )
        return {
            "items": [self._decode(row) for row in rows[:limit]],
            "next_cursor": rows[limit - 1]["sequence"] if len(rows) > limit else None,
        }
