# SPDX-License-Identifier: MIT
from dataclasses import dataclass

from kyno.wire.delivery import RecordingStatus


@dataclass(frozen=True)
class RecordingReceipt:
    """The server's recording outcome for a direction read."""

    status: RecordingStatus
    record_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", RecordingStatus(self.status))
        if self.record_id is not None and not isinstance(self.record_id, str):
            raise TypeError("record_id must be text or None")
        if self.status is RecordingStatus.RECORDED:
            if self.record_id is None or not self.record_id.strip():
                raise ValueError("recorded requires a nonempty record_id")
        elif self.record_id is not None:
            raise ValueError("disabled and failed cannot have a record_id")
