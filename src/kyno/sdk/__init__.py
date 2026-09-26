# SPDX-License-Identifier: MIT
"""The Kyno SDK: connect to a control plane and bind steps to the direction
in force.

    import kyno

    connection = kyno.connect(url="http://localhost:8080/mcp", token="...")
    binder = connection.binder()

    # in your orchestrator's before-each-step hook:
    block = binder.bind().render()

Everything an adapter needs is exported here; the framework adapters in
`kyno.adapters` are thin layers over this module.
"""

import kyno.config as _config
import kyno.sdk.client as _client
import kyno.sdk.history as _history
from kyno.sdk.binder import DirectionBinder
from kyno.sdk.binding import BindingStatus, DirectionBinding
from kyno.sdk.cell import (
    DIRECTION_MARKER,
    Direction,
    is_direction_block,
    refresh,
)
from kyno.sdk.client import (
    DirectionResponse,
    DirectionSource,
    LocalDirectionSource,
)
from kyno.sdk.plan import PlanTracker
from kyno.sdk.policy import PullPolicy
from kyno.sdk.recording import RecordingReceipt
from kyno.wire.delivery import RecordingStatus
from kyno.wire.delivery_record import DeliveryPage, DeliveryRecord, DeliverySummary
from kyno.wire.models import DetailLevel

__all__ = [
    "DeliveryPage",
    "DeliveryRecord",
    "DeliverySummary",
    "BindingStatus",
    "DirectionBinding",
    "DIRECTION_MARKER",
    "Direction",
    "DirectionBinder",
    "DirectionSource",
    "DirectionResponse",
    "RecordingReceipt",
    "RecordingStatus",
    "DetailLevel",
    "KynoConnection",
    "LocalDirectionSource",
    "PlanTracker",
    "PullPolicy",
    "connect",
    "is_direction_block",
    "refresh",
]


class KynoConnection:
    """One open session to a control plane, handing out binders that share it."""

    def __init__(self, runner: _client.SessionRunner) -> None:
        self._runner = runner

    def binder(
        self,
        constitution_key: str = "default",
        *,
        policy: PullPolicy | None = None,
        detail: str | DetailLevel = DetailLevel.COMPACT,
        correlation_id: str | None = None,
        metadata: dict | None = None,
    ) -> DirectionBinder:
        """Create a binder with private fallback state for the named constitution.

        Pass the constitution's key, not its content. The default key is "default".
        """
        source = _client.McpDirectionSource(
            self._runner, correlation_id=correlation_id, metadata=metadata
        )
        return DirectionBinder(source, constitution_key, policy=policy, detail=detail)

    def close(self) -> None:
        self._runner.close()

    def get_delivery_record(self, record_id: str) -> DeliveryRecord:
        """Return the persisted delivery reference and delta for one record.

        Raises ValueError for an empty or non-string ID, KynoHistoryError
        for a rejected query, and KynoUnavailableError for transport or reply failures.
        """
        return _history.get_delivery_record(self._runner, record_id)

    def get_constitution(
        self,
        constitution_key: str = "default",
        *,
        version: int | None = None,
        detail: str | DetailLevel = DetailLevel.COMPACT,
    ) -> Direction:
        """Return current direction or an exact version in the requested detail.

        Compact detail is the default. It retains the mission and principle
        titles, omitting declaration and principle descriptions as agent reads do.
        Version zero reads the empty direction. Reads use Core's recording policy
        and do not update binder fallback state. Returned direction has no per-delivery
        delta or recent change notes. Raises ValueError for invalid arguments,
        KynoHistoryError for absent exact versions or rejected queries, and
        KynoUnavailableError for transport or reply failures.
        """
        return _history.get_constitution(
            self._runner, constitution_key, version=version, detail=detail
        )

    def list_delivery_records(
        self,
        *,
        correlation_id: str | None = None,
        constitution: str | None = None,
        since: str | None = None,
        until: str | None = None,
        after: int | None = None,
        limit: int = 50,
    ) -> DeliveryPage:
        """List delivery records in insertion order, without deltas or direction content.

        Pass next_cursor as after with the same filters to fetch another page.
        Timestamps are inclusive ISO timestamps with a timezone. Omitted filters
        include all records. Raises KynoHistoryError for rejected queries and
        KynoUnavailableError for transport or reply failures.
        """
        return _history.list_delivery_records(
            self._runner,
            correlation_id=correlation_id,
            constitution=constitution,
            since=since,
            until=until,
            after=after,
            limit=limit,
        )

    def __enter__(self) -> "KynoConnection":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


def connect(
    profile: str | None = None, *, url: str | None = None, token: str | None = None
) -> KynoConnection:
    """Open a session to a Kyno serving MCP over HTTP.

    With no URL, resolve the named profile or the default profile. Explicit
    values are accepted for applications that own their wiring; the SDK never
    chooses environment variable names or falls back between sources.
    """
    if profile is not None and url is not None:
        raise _config.ProfileError(
            "profile and url cannot be combined; choose one connection source"
        )
    if url is not None:
        if token is None or not token.strip():
            raise _config.ProfileError("explicit url requires token")
        binding = _client.KynoBinding(
            endpoint=_config.normalize_endpoint(url, profile=False), token=token
        )
    else:
        selected_profile = _config.DEFAULT_PROFILE if profile is None else profile
        resolved = _config.resolve(selected_profile, token_override=token)
        binding = _client.KynoBinding(
            endpoint=_config.normalize_endpoint(resolved.url, profile=True),
            token=resolved.token,
        )
    runner = _client.SessionRunner(_client.http_session(binding))
    runner.start()
    return KynoConnection(runner)
