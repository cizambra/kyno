# SPDX-License-Identifier: MIT
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

logger = logging.getLogger("kyno.adapters")


class EventType(StrEnum):
    PULL_FAILED_STALE = "pull_failed_stale"
    PULL_FAILED_EMPTY = "pull_failed_empty"
    UNCHECKED = "unchecked"
    DRIFT_BLOCKED = "drift_blocked"
    DRIFT_PAUSED = "drift_paused"
    PAUSE_UNSUPPORTED = "pause_unsupported"


@dataclass(frozen=True)
class TelemetryEvent:
    kind: EventType
    constitution: str
    version: int
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "kind": self.kind.value,
            "constitution": self.constitution,
            "version": self.version,
            "detail": self.detail,
        }


class TelemetrySink(Protocol):
    def emit(self, event: TelemetryEvent) -> None: ...


class LogSink:
    def emit(self, event: TelemetryEvent) -> None:
        logger.warning(
            "kyno %s constitution=%s version=%s %s",
            event.kind,
            event.constitution,
            event.version,
            event.detail,
        )


@dataclass
class RecordingSink:
    events: list[TelemetryEvent] = field(default_factory=list)

    def emit(self, event: TelemetryEvent) -> None:
        self.events.append(event)
