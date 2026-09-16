# SPDX-License-Identifier: MIT
from typing import TypeVar

from pydantic import TypeAdapter

from kyno.sdk.client import SessionRunner, _payload
from kyno.sdk.errors import KynoHistoryError, KynoUnavailableError
from kyno.wire.delivery_record import DeliveryPage, DeliveryRecord

HistoryResult = TypeVar("HistoryResult")
_record = TypeAdapter(DeliveryRecord)
_page = TypeAdapter(DeliveryPage)


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
