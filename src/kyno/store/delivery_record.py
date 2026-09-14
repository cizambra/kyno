from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Engine, insert, select

from kyno.store.schema import build_metadata


class SqlDeliveryRecordStore:
    def __init__(self, engine: Engine, prefix: str = "kyno_") -> None:
        self._engine = engine
        metadata, self._constitutions, *_ = build_metadata(prefix)
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
        """Persist a direction snapshot atomically and return its unique record ID."""
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
            "direction": json.dumps(direction, allow_nan=False),
            "requester": json.dumps(requester, allow_nan=False),
            "session_id": context["session_id"],
            "metadata": json.dumps(context["metadata"], allow_nan=False),
        }
        with self._engine.begin() as connection:
            constitution_id = None
            if values["served_version"]:
                constitution_id = connection.scalar(
                    select(self._constitutions.c.id).where(
                        self._constitutions.c.name == constitution
                    )
                )
            connection.execute(
                insert(self._table).values(constitution_id=constitution_id, **values)
            )
        return identifier
