# SPDX-License-Identifier: MIT
from __future__ import annotations

from kyno.sdk.cell import Direction, DirectionCell, check_context
from kyno.sdk.client import DirectionSource
from kyno.sdk.errors import KynoUnavailableError
from kyno.sdk.policy import PullPolicy
from kyno.sdk.telemetry import (
    EventType,
    LogSink,
    TelemetryEvent,
    TelemetrySink,
)
from kyno.wire.errors import CoherenceError
from kyno.wire.models import DetailLevel


class DirectionBinder:
    """Bind the next step to the version in force right now.

    Shipped adapters pull at every step boundary. The successful response
    becomes the latest-known direction in the cell and remains available as
    the fallback if a later pull cannot reach Kyno.
    """

    def __init__(
        self,
        source: DirectionSource,
        cell: DirectionCell | None = None,
        policy: PullPolicy | None = None,
        telemetry: TelemetrySink | None = None,
        context: str | DetailLevel = DetailLevel.COMPACT,
    ) -> None:
        self._source = source
        self.cell = cell if cell is not None else DirectionCell()
        self._policy = policy or PullPolicy()
        self._telemetry = telemetry or LogSink()
        # Checked here rather than at the first step, so a typo fails while the integration is
        # being set up instead of once it is running.
        self.context = check_context(context)

    def bind(self, constitution: str = "default") -> Direction:
        known = self.cell.known_version(constitution)
        try:
            changes = self._source.changes_since(known, constitution, self.context)
        except (CoherenceError, OSError) as exc:
            # OSError covers the socket family and, since 3.10, TimeoutError;
            # CoherenceError covers everything kyno raises, including the
            # adapters' KynoUnavailableError.
            return self._degrade(constitution, exc)
        return self.cell.update(Direction.from_changes(changes, constitution, self.context))

    def _degrade(self, constitution: str, exc: Exception) -> Direction:
        last = self.cell.get(constitution)
        if self._policy.fail_closed:
            raise KynoUnavailableError(f"cannot reach kyno for '{constitution}': {exc}") from exc
        if last is not None:
            self._emit(EventType.PULL_FAILED_STALE, constitution, last.version, str(exc))
            return last
        self._emit(EventType.PULL_FAILED_EMPTY, constitution, 0, str(exc))
        return Direction.empty(constitution, self.context)

    def plan(self, constitution: str = "default"):
        from kyno.sdk.plan import PlanTracker

        return PlanTracker(self, constitution)

    def _emit(self, kind: EventType, constitution: str, version: int, detail: str) -> None:
        self._telemetry.emit(
            TelemetryEvent(kind=kind, constitution=constitution, version=version, detail=detail)
        )
