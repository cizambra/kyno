# SPDX-License-Identifier: MIT
from typing import TypedDict

from pydantic import JsonValue


class DeliveryRecord(TypedDict):
    record_id: str
    recorded_at: str
    constitution_id: int | None
    requested_constitution: str
    served_version: int
    operation: str
    known_version: int | None
    detail_level: str | None
    selection: dict[str, JsonValue]
    direction: dict[str, JsonValue]
    requester: dict[str, JsonValue] | None
    session_id: str | None
    metadata: dict[str, JsonValue]
