# SPDX-License-Identifier: MIT
from typing import NotRequired, TypeVar

from pydantic import TypeAdapter
from typing_extensions import TypedDict

from kyno.sdk.cell import Direction
from kyno.sdk.client import SessionRunner, _payload
from kyno.sdk.errors import KynoHistoryError, KynoUnavailableError
from kyno.wire.constitution import check_constitution_key
from kyno.wire.delivery_record import DeliveryPage, DeliveryRecord
from kyno.wire.models import DetailLevel, check_detail


class _ConstitutionPrinciple(TypedDict):
    title: str
    description: NotRequired[str]


class _Constitution(TypedDict):
    constitution_key: str
    version: int
    mission: str
    declaration: NotRequired[str]
    principles: list[_ConstitutionPrinciple]


HistoryResult = TypeVar("HistoryResult")
_record = TypeAdapter(DeliveryRecord)
_page = TypeAdapter(DeliveryPage)
_constitution = TypeAdapter(_Constitution)


def _query(
    runner: SessionRunner, operation: str, arguments: dict, adapter: TypeAdapter[HistoryResult]
) -> HistoryResult:
    async def call(session):
        return await session.call_tool(operation, arguments)

    try:
        reply = runner.call(call)
        if reply.isError:
            raise KynoHistoryError(reply.content[0].text)
        return adapter.validate_python(_payload(reply), strict=True)
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
    constitution_key: str | None = None,
    since: str | None = None,
    until: str | None = None,
    after: int | None = None,
    limit: int = 50,
) -> DeliveryPage:
    if constitution_key is not None:
        constitution_key = check_constitution_key(constitution_key)
    filters = {
        "correlation_id": correlation_id,
        "constitution_key": constitution_key,
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


def get_constitution(
    runner: SessionRunner,
    constitution_key: str | None = None,
    *,
    version: int | None = None,
    detail: str | DetailLevel = DetailLevel.COMPACT,
) -> Direction:
    detail = check_detail(detail)
    if version is not None and (type(version) is not int or version < 0):
        raise ValueError("version must be a non-negative integer")
    arguments: dict[str, object] = {"detail": detail.value}
    if constitution_key is not None:
        constitution_key = check_constitution_key(constitution_key)
        arguments["constitution_key"] = constitution_key
    if version is not None:
        arguments["version"] = version
    row = _query(runner, "get_constitution", arguments, _constitution)
    if row["version"] < 0 or (version is not None and row["version"] != version):
        raise KynoUnavailableError("bad reply from kyno: unexpected constitution version")
    try:
        row["constitution_key"] = check_constitution_key(row["constitution_key"])
        if constitution_key is not None and row["constitution_key"] != constitution_key:
            raise ValueError("unexpected constitution key")
        return Direction(
            constitution_key=row["constitution_key"],
            version=row["version"],
            mission=row["mission"],
            declaration=row.get("declaration", ""),
            principles=tuple(row["principles"]),
            detail=detail,
        )
    except Exception as exc:
        raise KynoUnavailableError(f"bad reply from kyno: {exc}") from exc
