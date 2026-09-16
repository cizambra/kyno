# SPDX-License-Identifier: MIT
from dataclasses import dataclass
from enum import StrEnum

from kyno.sdk.cell import Direction
from kyno.sdk.recording import RecordingReceipt


class DeliveryStatus(StrEnum):
    """How a binding obtained its direction, not whether it is still the newest version."""

    CURRENT = "current"
    CACHED = "cached"
    EMPTY = "empty"


@dataclass(frozen=True)
class DirectionBinding:
    """A direction snapshot and its delivery status for one binding operation."""

    direction: Direction
    status: DeliveryStatus
    recording: RecordingReceipt | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", DeliveryStatus(self.status))
