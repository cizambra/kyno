# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
import json
import os
import threading
from collections.abc import Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from kyno.errors import KynoUnavailableError
from kyno.models import COMPACT, ChangesSince


@dataclass(frozen=True)
class KynoBinding:
    """What an integrator is wired to: an endpoint, a credential, and the
    name of the constitution it serves. The name is part of the binding
    because "which direction was this agent on" must be answerable from the
    adapter, not from a config file somewhere else."""

    constitution: str = "default"
    endpoint: str | None = None
    # repr=False: bindings travel into logs and tracebacks; the credential must not.
    token: str | None = field(default=None, repr=False)

    @classmethod
    def from_env(cls, constitution: str = "default") -> KynoBinding:
        return cls(
            constitution=constitution,
            endpoint=os.environ.get("KYNO_URL") or None,
            token=os.environ.get("KYNO_TOKEN") or None,
        )


@runtime_checkable
class DirectionSource(Protocol):
    def changes_since(
        self, known_version: int, constitution: str, detail: str = COMPACT
    ) -> ChangesSince: ...


@runtime_checkable
class ControlPlaneProjection(Protocol):
    """The projection of a control plane that this source uses: answering
    what changed since a known version. Any object with that method fits.
    A protocol, so the MIT-licensed SDK never depends on the control
    plane's code."""

    def changes_since(
        self, known_version: int, constitution: str | None = None
    ) -> ChangesSince: ...


class LocalDirectionSource:
    """The control plane in this process -- what an embedding host and the
    tests use."""

    def __init__(self, control_plane: ControlPlaneProjection) -> None:
        self._control_plane = control_plane

    def changes_since(
        self, known_version: int, constitution: str, detail: str = COMPACT
    ) -> ChangesSince:
        # `detail` is a wire economy, and there is no wire here: the control
        # plane hands back the whole version either way.
        return self._control_plane.changes_since(known_version, constitution)


class SessionRunner:
    """One long-lived MCP session on a private event loop in a daemon thread.

    Orchestrator hooks are ordinary sync callables, so the async session
    needs a home that outlives a single call; a thread of our own also keeps
    us out of whatever loop the host application is running.
    """

    def __init__(self, connect: Callable[..., Any], timeout: float = 10.0) -> None:
        self._connect = connect
        self._timeout = timeout
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._session: Any = None
        self._ready = threading.Event()
        self._error: BaseException | None = None
        self._stop: asyncio.Event | None = None
        self._message_handler: Callable[[Any], Any] | None = None

    def set_message_handler(self, handler: Callable[[Any], Any]) -> None:
        """Must be set before start(): the handler is passed to the session
        when it is opened, and the session is opened once."""
        if self._thread is not None:
            raise RuntimeError("set_message_handler must be called before start()")
        self._message_handler = handler

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="kyno-mcp", daemon=True)
        self._thread.start()
        if not self._ready.wait(self._timeout):
            raise KynoUnavailableError("timed out opening the kyno MCP session")
        if self._error is not None:
            raise KynoUnavailableError(f"cannot open the kyno MCP session: {self._error}")

    def _run(self) -> None:
        asyncio.run(self._main())

    async def _main(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._stop = asyncio.Event()
        try:
            async with self._connect(message_handler=self._message_handler) as session:
                self._session = session
                self._ready.set()
                await self._stop.wait()
        except Exception as exc:
            # Reported through start()/call() as KynoUnavailableError: a
            # thread that dies quietly would look like a hung control plane.
            self._error = exc
            self._ready.set()
        finally:
            self._session = None

    def call(self, fn: Callable[[Any], Any]) -> Any:
        loop, session = self._loop, self._session
        if loop is None or session is None or loop.is_closed():
            raise KynoUnavailableError("the kyno MCP session is not open")
        try:
            future = asyncio.run_coroutine_threadsafe(fn(session), loop)
        except RuntimeError as exc:
            # The loop closed between the check above and this call: the
            # session is gone, which is the same answer as never having one.
            raise KynoUnavailableError(f"the kyno MCP session is not open: {exc}") from exc
        try:
            return future.result(self._timeout)
        except TimeoutError as exc:
            future.cancel()
            raise KynoUnavailableError("timed out talking to kyno") from exc

    def close(self) -> None:
        if self._loop is not None and self._stop is not None and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._stop.set)
        if self._thread is not None:
            self._thread.join(timeout=self._timeout)
        self._session = None


@asynccontextmanager
async def _http_session(binding: KynoBinding, message_handler=None):
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    headers = {"Authorization": f"Bearer {binding.token}"} if binding.token else None
    async with (
        streamablehttp_client(binding.endpoint, headers=headers) as (read, write, _id),
        ClientSession(read, write, message_handler=message_handler) as session,
    ):
        await session.initialize()
        yield session


def http_session(binding: KynoBinding):
    """A `connect` factory for SessionRunner over streamable-HTTP.
    The token is held here and never travels into integrator state or a
    checkpoint, which may be persisted."""
    if not binding.endpoint:
        raise KynoUnavailableError("no KYNO_URL configured for this binding")

    def connect(message_handler=None):
        return _http_session(binding, message_handler=message_handler)

    return connect


# A reply is one constitution, and a large one is a few hundred kilobytes.
# Measured in characters, which is the cheap proxy for bytes and needs no
# second copy of the text to check.
MAX_REPLY_CHARS = 8 * 1024 * 1024


def _payload(reply) -> dict:
    text = reply.content[0].text
    if len(text) > MAX_REPLY_CHARS:
        raise ValueError(f"reply is {len(text)} characters, over the {MAX_REPLY_CHARS} limit")
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise TypeError(f"expected an object, got {type(payload).__name__}")
    return payload


def _version(value) -> int:
    """A version is compared against the last one held, so a string here
    poisons that comparison for the life of the process."""
    version = int(value)
    if version < 0:
        raise ValueError(f"version {version} is negative")
    return version


def _text(value) -> str:
    # A number in a text field is coerced rather than refused -- it is
    # readable, and losing the direction over it would cost more. Null is not:
    # "None" in an agent's instructions is worse than a refused pull.
    if isinstance(value, str):
        return value
    if isinstance(value, int | float) and not isinstance(value, bool):
        return str(value)
    raise TypeError(f"expected text, got {type(value).__name__}")


def _sequence(value, field: str) -> tuple:
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise TypeError(f"{field} must be a list, got {type(value).__name__}")
    return tuple(value)


def _changes(payload: dict) -> ChangesSince:
    return ChangesSince(
        current_version=_version(payload["current_version"]),
        changed=bool(payload["changed"]),
        mission=_text(payload["mission"]),
        principles=_sequence(payload["principles"], "principles"),
        # Absent at compact detail, and absent from a Kyno older than
        # declarations -- neither is a reason to fail a pull.
        declaration=_text(payload.get("declaration", "")),
        changed_mission=bool(payload["changed_mission"]),
        changed_principles=bool(payload["changed_principles"]),
        change_notes=tuple(
            _text(note) for note in _sequence(payload["change_notes"], "change_notes")
        ),
        # Absent from a Kyno older than the delta: a pull that still answers
        # with the direction is not a failure, it just says less.
        delta=tuple(_text(line) for line in _sequence(payload.get("delta", []), "delta")),
    )


class McpDirectionSource:
    """Pulls direction over MCP, by constitution name."""

    def __init__(self, runner: SessionRunner) -> None:
        self._runner = runner

    def changes_since(
        self, known_version: int, constitution: str, detail: str = COMPACT
    ) -> ChangesSince:
        """Every way this can fail arrives as KynoUnavailableError, because
        that is what the binder's policy degrades on. A reply we cannot read
        is the control plane being unreachable as far as the next step is
        concerned, and it must cost freshness rather than the step itself."""

        async def call(session):
            return await session.call_tool(
                "get_changes_since",
                {
                    "known_version": known_version,
                    "constitution": constitution,
                    "detail": detail,
                },
            )

        try:
            return _changes(_payload(self._runner.call(call)))
        except KynoUnavailableError:
            raise  # already the right answer, with a better reason than ours
        except Exception as exc:
            raise KynoUnavailableError(f"bad reply from kyno: {exc}") from exc
