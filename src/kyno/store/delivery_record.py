from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

from sqlalchemy import Engine, insert, select

from kyno.store.schema import build_metadata
from kyno.wire.delivery_record import DeliveryRecord


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


class SqlDeliveryRecordStore:
    def __init__(self, engine: Engine, prefix: str = "kyno_") -> None:
        self._engine = engine
        metadata, self._constitutions, self._versions, _ = build_metadata(prefix)
        self._table = metadata.tables[f"{prefix}delivery_records"]

    def append(
        self,
        direction: dict,
        *,
        operation: str,
        constitution: str,
        arguments: dict,
        context: dict,
        requester: dict | None = None,
    ) -> str:
        """Record the served version reference and returned delta atomically."""
        identifier = str(uuid4())
        values = {
            "record_id": identifier,
            "recorded_at": datetime.now(UTC).isoformat(timespec="microseconds"),
            "requested_constitution": constitution,
            "served_version": direction[
                "current_version" if operation == "get_changes_since" else "version"
            ],
            "operation": operation,
            "known_version": arguments.get("known_version"),
            "detail_level": arguments.get("detail"),
            "selection": json.dumps(
                {key: arguments[key] for key in ("title",) if key in arguments}
            ),
            "delta": json.dumps(direction.get("delta"), allow_nan=False),
            "requester": json.dumps(requester, allow_nan=False),
            "correlation_id": context["correlation_id"],
            "metadata": json.dumps(context["metadata"], allow_nan=False),
        }
        with self._engine.begin() as connection:
            constitution_id = None
            if values["served_version"]:
                constitution_id = connection.scalar(
                    select(self._constitutions.c.id)
                    .join(self._versions)
                    .where(
                        self._constitutions.c.name == constitution,
                        self._versions.c.version == values["served_version"],
                    )
                )
                if constitution_id is None:
                    raise ValueError("served constitution version not found")
            connection.execute(
                insert(self._table).values(constitution_id=constitution_id, **values)
            )
        return identifier

    def _decode(self, row) -> DeliveryRecord:
        record = dict(row)
        record.pop("sequence")
        for key in ("delta", "requester", "metadata", "selection"):
            record[key] = json.loads(record[key])
        return cast(DeliveryRecord, record)

    def get(self, record_id: str) -> DeliveryRecord:
        """Return the version reference and saved delta, or raise for an unknown ID."""
        with self._engine.connect() as connection:
            row = (
                connection.execute(select(self._table).where(self._table.c.record_id == record_id))
                .mappings()
                .first()
            )
        if row is None:
            raise ValueError("delivery record not found")
        return self._decode(row)

    def list(
        self,
        *,
        correlation_id: str | None = None,
        constitution: str | None = None,
        since: str | None = None,
        until: str | None = None,
        after: int = 0,
        limit: int = 50,
    ) -> dict:
        """Return an insertion-ordered page and its next cursor, or None at the end.

        Time bounds are inclusive. Continue with the same filters and the returned
        cursor as after; records appended between pages can appear on later pages.
        """
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("limit must be an integer from 1 to 100")
        if type(after) is not int or after < 0:
            raise ValueError("after must be a nonnegative integer")
        since, until = _timestamp(since), _timestamp(until)
        if since and until and since > until:
            raise ValueError("since must not be later than until")
        query = select(self._table).where(self._table.c.sequence > after)
        for column, value in (
            (self._table.c.correlation_id, correlation_id),
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
