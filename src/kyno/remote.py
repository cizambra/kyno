"""The CLI's remote side: dial a profile's endpoint and speak MCP.

A remote run resolves a profile to a URL and a token, opens one MCP
session against the server's /mcp endpoint, and asks the same questions
the local path asks its own store. The session machinery is the SDK's;
this module only makes it comfortable for one-shot commands.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from kyno.errors import CoherenceError, KynoUnavailableError
from kyno.models import ConstitutionVersion, normalize_principles
from kyno.profiles import Resolved, resolve
from kyno.sdk.client import KynoBinding, SessionRunner, http_session


class RemoteError(CoherenceError):
    """The server answered with a refusal, quoted as it said it."""


class RemoteClient:
    """One MCP session against one resolved profile, for one command."""

    def __init__(self, resolved: Resolved) -> None:
        binding = KynoBinding(endpoint=resolved.url.rstrip("/") + "/mcp", token=resolved.token)
        self.profile = resolved.profile
        self.url = resolved.url
        self._runner = SessionRunner(http_session(binding))

    def open(self) -> None:
        try:
            self._runner.start()
        except KynoUnavailableError as exc:
            raise RemoteError(f"cannot reach '{self.profile}' at {self.url}: {exc}") from exc

    def close(self) -> None:
        self._runner.close()

    def call_tool(self, name: str, arguments: dict) -> Any:
        """One tool call, decoded. A server-side refusal comes back as a
        RemoteError carrying the server's own words."""
        reply = self._runner.call(lambda session: session.call_tool(name, arguments))
        text = reply.content[0].text if reply.content else ""
        if getattr(reply, "isError", False):
            raise RemoteError(text or f"the server refused {name}")
        return json.loads(text)


def dial(
    profile: str,
    *,
    credentials_profile: str | None = None,
    token_env: str | None = None,
) -> RemoteClient:
    """Resolve a profile and open a session against it. Anything that does
    not resolve or connect fails loudly before any command logic runs."""
    client = RemoteClient(
        resolve(profile, credentials_profile=credentials_profile, token_env=token_env)
    )
    client.open()
    return client


def version_from_payload(payload: dict) -> ConstitutionVersion | None:
    """A full-detail get_constitution payload as the version object the
    local code paths already know how to render. Version 0 is the empty
    state, which the local paths spell None."""
    if int(payload.get("version", 0)) == 0:
        return None
    raw = payload.get("created_at")
    try:
        created_at = datetime.fromisoformat(raw) if raw else datetime.now(UTC)
    except ValueError:
        created_at = datetime.now(UTC)
    principles = normalize_principles(tuple(payload.get("principles") or ()))
    return ConstitutionVersion(
        version=int(payload["version"]),
        mission=payload.get("mission") or "",
        declaration=payload.get("declaration") or "",
        principles=principles or (),
        change_note=payload.get("change_note") or "",
        changed_mission=bool(payload.get("changed_mission", False)),
        changed_principles=bool(payload.get("changed_principles", False)),
        created_at=created_at,
        created_by=payload.get("created_by"),
    )
