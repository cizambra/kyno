# SPDX-License-Identifier: MIT
from enum import StrEnum


class RecordingStatus(StrEnum):
    RECORDED = "recorded"
    DISABLED = "disabled"
    FAILED = "failed"


def recording_result(status: RecordingStatus, delivery_id: str | None = None) -> dict:
    return {"status": status.value, "delivery_id": delivery_id}
