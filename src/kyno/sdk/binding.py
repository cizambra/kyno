# SPDX-License-Identifier: MIT
from dataclasses import dataclass
from enum import StrEnum

from kyno.sdk.cell import Direction


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

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", DeliveryStatus(self.status))
