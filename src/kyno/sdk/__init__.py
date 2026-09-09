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
from kyno.sdk.binder import DirectionBinder
from kyno.sdk.cell import (
    DIRECTION_MARKER,
    Direction,
    DirectionCell,
    is_direction_block,
    refresh,
)
from kyno.sdk.client import DirectionSource, LocalDirectionSource
from kyno.sdk.gate import (
    Action,
    GateDecision,
    RealignmentGate,
    Verdict,
    VerdictSource,
)
from kyno.sdk.plan import PlanTracker
from kyno.sdk.policy import (
    GatePolicy,
    PullPolicy,
)
from kyno.sdk.telemetry import TelemetrySink
from kyno.wire.models import DetailLevel

__all__ = [
    "DIRECTION_MARKER",
    "Action",
    "GateDecision",
    "GatePolicy",
    "RealignmentGate",
    "Verdict",
    "VerdictSource",
    "Direction",
    "DirectionBinder",
    "DirectionCell",
    "DirectionSource",
    "DetailLevel",
    "KynoConnection",
    "LocalDirectionSource",
    "PlanTracker",
    "PullPolicy",
    "TelemetrySink",
    "connect",
    "is_direction_block",
    "refresh",
]


class KynoConnection:
    """One open session to a control plane, handing out binders that share it."""

    def __init__(self, runner: _client.SessionRunner) -> None:
        self._runner = runner
        self._source = _client.McpDirectionSource(runner)

    def binder(
        self,
        policy: PullPolicy | None = None,
        cell: DirectionCell | None = None,
        telemetry: TelemetrySink | None = None,
        context: str | DetailLevel = DetailLevel.COMPACT,
    ) -> DirectionBinder:
        return DirectionBinder(
            self._source, cell=cell, policy=policy, telemetry=telemetry, context=context
        )

    def close(self) -> None:
        self._runner.close()

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
