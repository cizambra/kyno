# SPDX-License-Identifier: MIT
from typing import TypeVar

from pydantic import TypeAdapter
from typing_extensions import TypedDict

from kyno.sdk.cell import Direction
from kyno.sdk.client import MAX_REPLY_CHARS, SessionRunner
from kyno.sdk.errors import KynoHistoryError, KynoUnavailableError
from kyno.wire.delivery_record import DeliveryPage, DeliveryRecord
from kyno.wire.models import DetailLevel


class _HistoricalPrinciple(TypedDict):
    title: str
    description: str


class _HistoricalVersion(TypedDict):
    version: int
    mission: str
    declaration: str
    principles: list[_HistoricalPrinciple]


HistoryResult = TypeVar("HistoryResult")
_record = TypeAdapter(DeliveryRecord)
_page = TypeAdapter(DeliveryPage)
_versions = TypeAdapter(list[_HistoricalVersion])


def _query(
    runner: SessionRunner, operation: str, arguments: dict, adapter: TypeAdapter[HistoryResult]
) -> HistoryResult:
    async def call(session):
        return await session.call_tool(operation, arguments)

    try:
        reply = runner.call(call)
        if reply.isError:
            raise KynoHistoryError(reply.content[0].text)
        text = reply.content[0].text
        if len(text) > MAX_REPLY_CHARS:
            raise ValueError(f"reply is {len(text)} characters, over the {MAX_REPLY_CHARS} limit")
        return adapter.validate_json(text, strict=True)
    except (KynoUnavailableError, KynoHistoryError):
        raise
    except Exception as exc:
        raise KynoUnavailableError(f"bad reply from kyno: {exc}") from exc


def get_delivery_record(runner: SessionRunner, record_id: str) -> DeliveryRecord:
    if not isinstance(record_id, str) or not record_id.strip():
        raise ValueError("record_id must be a non-empty string")
    return _query(runner, "get_delivery_record", {"record_id": record_id}, _record)


def list_delivery_records(
    runner: SessionRunner,
    *,
    correlation_id: str | None = None,
    constitution: str | None = None,
    since: str | None = None,
    until: str | None = None,
    after: int | None = None,
    limit: int = 50,
) -> DeliveryPage:
    filters = {
        "correlation_id": correlation_id,
        "constitution": constitution,
        "since": since,
        "until": until,
        "after": after,
        "limit": limit,
    }
    return _query(
        runner,
        "list_delivery_records",
        {key: value for key, value in filters.items() if value is not None},
        _page,
    )


def get_direction_version(
    runner: SessionRunner, version: int, constitution: str = "default"
) -> Direction | None:
    if type(version) is not int or version < 0:
        raise ValueError("version must be a non-negative integer")
    if not isinstance(constitution, str) or not constitution.strip():
        raise ValueError("constitution must be a non-empty string")
    if version == 0:
        return Direction.empty(constitution, context=DetailLevel.FULL)
    rows = _query(
        runner,
        "export_versions",
        {"constitution": constitution, "from_version": version, "to_version": version},
        _versions,
    )
    if not rows:
        return None
    if len(rows) != 1 or rows[0]["version"] != version:
        raise KynoUnavailableError("bad reply from kyno: expected only the requested version")
    row = rows[0]
    try:
        return Direction(
            constitution=constitution,
            version=version,
            mission=row["mission"],
            declaration=row["declaration"],
            principles=tuple(row["principles"]),
            context=DetailLevel.FULL,
        )
    except Exception as exc:
        raise KynoUnavailableError(f"bad reply from kyno: {exc}") from exc
