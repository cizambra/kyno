from __future__ import annotations

from kyno.adapters.core.cell import COMPACT, Direction, DirectionCell, check_context
from kyno.adapters.core.client import DirectionSource
from kyno.adapters.core.policy import (
    PULL_FAILED_EMPTY,
    PULL_FAILED_STALE,
    LogSink,
    PullPolicy,
    TelemetryEvent,
    TelemetrySink,
)
from kyno.errors import CoherenceError, KynoUnavailableError


class DirectionBinder:
    """Bind the next step to the version in force right now.

    Pull runs at every step boundary even when a push already refreshed the
    cell: the pull is cheap and self-describing, and the subscription's role
    is only to keep the stale-fallback fresher for the pulls that fail.
    """

    def __init__(
        self,
        source: DirectionSource,
        cell: DirectionCell | None = None,
        policy: PullPolicy | None = None,
        telemetry: TelemetrySink | None = None,
        context: str = COMPACT,
    ) -> None:
        self._source = source
        self.cell = cell if cell is not None else DirectionCell()
        self._policy = policy or PullPolicy()
        self._telemetry = telemetry or LogSink()
        # Checked here rather than at the first step, so a typo fails while
        # the integration is being wired instead of once it is already running.
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
            self._emit(PULL_FAILED_STALE, constitution, last.version, str(exc))
            return last
        self._emit(PULL_FAILED_EMPTY, constitution, 0, str(exc))
        return Direction.empty(constitution, self.context)

    def _emit(self, kind: str, constitution: str, version: int, detail: str) -> None:
        self._telemetry.emit(
            TelemetryEvent(kind=kind, constitution=constitution, version=version, detail=detail)
        )
