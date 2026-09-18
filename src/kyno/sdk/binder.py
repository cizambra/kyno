# SPDX-License-Identifier: MIT
from __future__ import annotations

import logging

from kyno.sdk.binding import DeliveryStatus, DirectionBinding
from kyno.sdk.cell import Direction, DirectionCell, check_context
from kyno.sdk.client import DirectionSource
from kyno.sdk.errors import KynoUnavailableError
from kyno.sdk.policy import PullPolicy
from kyno.wire.errors import CoherenceError
from kyno.wire.models import DetailLevel

logger = logging.getLogger(__name__)


class DirectionBinder:
    """Pull one constitution's direction for each step.

    Shipped adapters pull at every step boundary. The successful response
    becomes the latest-known direction in the cell and remains available as
    the fallback if a later pull cannot reach Kyno.
    """

    def __init__(
        self,
        source: DirectionSource,
        constitution: str = "default",
        *,
        policy: PullPolicy | None = None,
        context: str | DetailLevel = DetailLevel.COMPACT,
    ) -> None:
        if not isinstance(constitution, str):
            raise TypeError("constitution name must be a string")
        self._constitution = constitution
        self._source = source
        self._cell = DirectionCell()
        self._policy = policy or PullPolicy()
        # Checked here rather than at the first step, so a typo fails while the integration is
        # being set up instead of once it is running.
        self._context = check_context(context)

    @property
    def context(self) -> DetailLevel:
        """The context level selected when the binder was constructed."""
        return self._context

    @property
    def constitution(self) -> str:
        """The constitution name selected when the binder was constructed."""
        return self._constitution

    def bind(self) -> Direction:
        """Pull direction, applying the configured failure policy."""
        return self.bind_with_status().direction

    def bind_with_status(self) -> DirectionBinding:
        """Pull once and return direction with its per-call delivery status.

        Current identifies a successful read, including an unchanged or empty
        constitution. Cached identifies a retained value after failure or an
        older overlapping response. Empty identifies failure without a cached
        value. A fail-closed pull failure raises instead of returning a binding.
        """
        constitution = self.constitution
        last_seen_version = self._cell.last_seen_version()
        try:
            response = self._source.changes_since(last_seen_version, constitution, self.context)
        except (CoherenceError, OSError) as exc:
            # OSError covers the socket family and, since 3.10, TimeoutError;
            # CoherenceError covers everything kyno raises, including the
            # adapters' KynoUnavailableError.
            return self._degrade(constitution, exc)
        changes = response.changes
        direction, recording = self._cell.update_with_recording(
            Direction.from_changes(changes, constitution, self.context), response.recording
        )
        status = (
            DeliveryStatus.CACHED
            if direction.version > changes.current_version
            else DeliveryStatus.CURRENT
        )
        return DirectionBinding(direction, status, recording)

    def _degrade(self, constitution: str, exc: Exception) -> DirectionBinding:
        snapshot = self._cell.get_with_recording()
        if self._policy.fail_closed:
            raise KynoUnavailableError(f"cannot reach kyno for '{constitution}': {exc}") from exc
        if snapshot is not None:
            last, recording = snapshot
            logger.warning(
                "kyno pull_failed_cached constitution=%s version=%s %s",
                constitution,
                last.version,
                exc,
            )
            return DirectionBinding(last, DeliveryStatus.CACHED, recording)
        logger.warning("kyno pull_failed_empty constitution=%s version=0 %s", constitution, exc)
        return DirectionBinding(Direction.empty(constitution, self.context), DeliveryStatus.EMPTY)

    def plan(self):
        from kyno.sdk.plan import PlanTracker

        return PlanTracker(self)
