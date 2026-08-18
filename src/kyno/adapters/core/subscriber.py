from __future__ import annotations

import contextlib
import queue
import threading

import mcp.types as types
from pydantic import AnyUrl

from kyno.adapters.core.cell import Direction, DirectionCell
from kyno.adapters.core.client import DirectionSource, SessionRunner
from kyno.adapters.core.policy import (
    PULL_FAILED_STALE,
    LogSink,
    TelemetryEvent,
    TelemetrySink,
)
from kyno.mcp_server import RESOURCE_URI

_STOP = object()


class BackgroundSubscriber:
    """A push is a hint, not a payload.

    The notification says only "something changed"; every wake re-pulls by
    name, on a thread of its own so the event loop is never blocked by a
    call it would have to serve itself.
    """

    def __init__(
        self,
        runner: SessionRunner,
        source: DirectionSource,
        cell: DirectionCell,
        constitutions: tuple[str, ...] = ("default",),
        telemetry: TelemetrySink | None = None,
    ) -> None:
        self._runner = runner
        self._source = source
        self._cell = cell
        self._constitutions = tuple(constitutions)
        self._telemetry = telemetry or LogSink()
        # One slot: a wake means "re-pull everything by name", so pending
        # wakes coalesce and a notification flood cannot grow memory.
        self._wakes: queue.Queue = queue.Queue(maxsize=1)
        self._worker: threading.Thread | None = None
        self._progress = threading.Condition()
        self.refreshes = 0

    def start(self) -> None:
        self._runner.set_message_handler(self._on_message)
        self._runner.start()
        self._runner.call(lambda session: session.subscribe_resource(AnyUrl(RESOURCE_URI)))
        self._worker = threading.Thread(target=self._refresh_loop, name="kyno-sub", daemon=True)
        self._worker.start()
        self.notify()

    def stop(self) -> None:
        if self._worker is not None:
            # Blocking on purpose: a pending wake occupies the one slot until
            # the worker drains it, and the worker always comes back for more.
            self._wakes.put(_STOP)
            self._worker.join(timeout=5.0)
            self._worker = None
        self._runner.close()

    def notify(self) -> None:
        # Full means a wake is already pending, and one is the whole message.
        with contextlib.suppress(queue.Full):
            self._wakes.put_nowait(None)

    async def _on_message(self, message) -> None:
        if isinstance(message, types.ServerNotification) and isinstance(
            message.root, types.ResourceUpdatedNotification
        ):
            self.notify()

    def _refresh_loop(self) -> None:
        while True:
            item = self._wakes.get()
            if item is _STOP:
                return
            for constitution in self._constitutions:
                self._refresh(constitution)
            with self._progress:
                self.refreshes += 1
                self._progress.notify_all()

    def _refresh(self, constitution: str) -> None:
        known = self._cell.known_version(constitution)
        try:
            changes = self._source.changes_since(known, constitution)
        except Exception as exc:
            # A failed re-pull must not kill this thread: the next wake, or
            # the next pull-before-step, still binds the current version.
            self._telemetry.emit(
                TelemetryEvent(
                    kind=PULL_FAILED_STALE,
                    constitution=constitution,
                    version=known,
                    detail=str(exc),
                )
            )
            return
        self._cell.update(Direction.from_changes(changes, constitution))
        with self._progress:
            self._progress.notify_all()

    def wait_for_version(self, constitution: str, version: int, timeout: float = 5.0) -> bool:
        with self._progress:
            return self._progress.wait_for(
                lambda: self._cell.known_version(constitution) >= version, timeout=timeout
            )

    def wait_for_refresh(self, count: int, timeout: float = 5.0) -> bool:
        with self._progress:
            return self._progress.wait_for(lambda: self.refreshes >= count, timeout=timeout)
