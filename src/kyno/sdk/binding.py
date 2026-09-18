# SPDX-License-Identifier: MIT
from dataclasses import dataclass
from enum import StrEnum

from kyno.sdk.cell import Direction
from kyno.sdk.recording import RecordingReceipt


class BindingStatus(StrEnum):
    """How a binding obtained its direction, not whether it is still the newest version."""

    PULLED = "pulled"
    CACHED = "cached"
    EMPTY = "empty"


@dataclass(frozen=True)
class DirectionBinding:
    """A direction snapshot and its binding status for one binding operation."""

    direction: Direction
    status: BindingStatus
    recording: RecordingReceipt | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", BindingStatus(self.status))
