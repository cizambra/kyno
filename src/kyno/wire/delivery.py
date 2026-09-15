# SPDX-License-Identifier: MIT
from enum import StrEnum


class RecordingStatus(StrEnum):
    RECORDED = "recorded"
    DISABLED = "disabled"
    FAILED = "failed"


def recording_result(status: RecordingStatus, record_id: str | None = None) -> dict:
    """Return the recording status and its record ID, if one was persisted."""
    return {"status": status.value, "record_id": record_id}
