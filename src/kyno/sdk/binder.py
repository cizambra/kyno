# SPDX-License-Identifier: MIT
from __future__ import annotations

import logging
from threading import Lock

from kyno.sdk.binding import BindingStatus, DirectionBinding
from kyno.sdk.cell import Direction, DirectionCell
from kyno.sdk.client import DirectionSource
from kyno.sdk.errors import KynoUnavailableError
from kyno.sdk.policy import PullPolicy
from kyno.wire.constitution import check_constitution_key
from kyno.wire.errors import CoherenceError
from kyno.wire.models import DetailLevel, check_detail

logger = logging.getLogger(__name__)


class DirectionBinder:
    """Pull one constitution's direction for each step.

    Shipped adapters pull at every step boundary. The successful response
    becomes the binder's latest-known direction and remains available as
    the fallback if a later pull cannot reach Kyno.
    """

    def __init__(
        self,
        source: DirectionSource,
        constitution_key: str | None = None,
        *,
        policy: PullPolicy | None = None,
        detail: str | DetailLevel = DetailLevel.COMPACT,
    ) -> None:
        self._constitution_key = (
            check_constitution_key(constitution_key) if constitution_key is not None else None
        )
        self._resolution_lock = Lock()
        self._source = source
        self._cell = DirectionCell()
        self._policy = policy or PullPolicy()
        # Checked here rather than at the first step, so a typo fails while the integration is
        # being set up instead of once it is running.
        self._detail = check_detail(detail)

    @property
    def detail(self) -> DetailLevel:
        """The detail level selected when the binder was constructed."""
        return self._detail

    @property
    def constitution_key(self) -> str | None:
        """The selected key, or None until Core resolves an omitted selection."""
        return self._constitution_key

    def bind(self) -> Direction:
        """Pull direction, applying the configured failure policy."""
        return self.bind_with_status().direction

    def bind_with_status(self) -> DirectionBinding:
        """Pull once and return direction with its per-call binding status.

        Pulled identifies a successful read, including an unchanged or empty
        constitution. Cached identifies a retained value after failure or an
        older overlapping response. Empty identifies failure without a cached
        value. A fail-closed pull failure raises instead of returning a binding.
        """
        if self.constitution_key is None:
            with self._resolution_lock:
                return self._bind_with_status()
        return self._bind_with_status()

    def _bind_with_status(self) -> DirectionBinding:
        constitution_key = self.constitution_key
        last_seen_version = self._cell.last_seen_version()
        try:
            response = self._source.changes_since(last_seen_version, constitution_key, self.detail)
            changes = response.changes
            if changes.constitution_key is None:
                raise KynoUnavailableError("direction reply has no resolved constitution key")
            if constitution_key is not None and changes.constitution_key != constitution_key:
                raise KynoUnavailableError("direction reply has an unexpected constitution key")
        except (CoherenceError, OSError) as exc:
            # OSError covers the socket family and, since 3.10, TimeoutError;
            # CoherenceError covers everything kyno raises, including the
            # adapters' KynoUnavailableError.
            return self._degrade(constitution_key, exc)
        direction, recording = self._cell.update_with_recording(
            Direction.from_changes(changes, changes.constitution_key, self.detail),
            response.recording,
        )
        self._constitution_key = direction.constitution_key
        status = (
            BindingStatus.CACHED
            if direction.version > changes.current_version
            else BindingStatus.PULLED
        )
        return DirectionBinding(direction, status, recording)

    def _degrade(self, constitution_key: str | None, exc: Exception) -> DirectionBinding:
        snapshot = self._cell.get_with_recording()
        if self._policy.fail_closed:
            raise KynoUnavailableError(
                f"cannot reach kyno for '{constitution_key}': {exc}"
            ) from exc
        if snapshot is not None:
            last, recording = snapshot
            logger.warning(
                "kyno pull_failed_cached constitution_key=%s version=%s %s",
                constitution_key,
                last.version,
                exc,
            )
            return DirectionBinding(last, BindingStatus.CACHED, recording)
        logger.warning(
            "kyno pull_failed_empty constitution_key=%s version=0 %s", constitution_key, exc
        )
        return DirectionBinding(Direction.empty(constitution_key, self.detail), BindingStatus.EMPTY)

    def plan(self):
        from kyno.sdk.plan import PlanTracker

        return PlanTracker(self)
