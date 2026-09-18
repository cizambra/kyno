"""Local and MCP sources return the same constitution content for the selected detail."""

import pytest

from kyno.sdk.cell import Direction
from kyno.sdk.client import LocalDirectionSource, McpDirectionSource
from kyno.wire.models import DetailLevel


@pytest.mark.parametrize("detail", ["compact", DetailLevel.COMPACT, "full", DetailLevel.FULL])
@pytest.mark.parametrize("last_seen_version", [0, 1, 2])
def test_given_rich_updates_when_changes_since_is_called_then_local_and_mcp_content_match(
    mcp_runner, detail, last_seen_version
):
    runner, control_plane = mcp_runner
    control_plane.apply_direction(
        mission="Support customers",
        declaration="Explain support decisions.",
        principles=[{"title": "Be clear", "description": "State the reason."}],
        change_note="Initial support direction",
        constitution="support",
    )
    control_plane.apply_direction(
        mission="Resolve support requests",
        declaration="Explain support decisions.",
        principles=[{"title": "Be clear", "description": "State the reason."}],
        change_note="Prioritize resolution",
        constitution="support",
    )
    original = control_plane.changes_since(last_seen_version, "support")

    local = LocalDirectionSource(control_plane).changes_since(last_seen_version, "support", detail)
    remote = McpDirectionSource(runner).changes_since(last_seen_version, "support", detail)

    assert local.changes == remote.changes
    assert local.recording is None
    assert local.changes.declaration == (
        "Explain support decisions." if detail == DetailLevel.FULL else ""
    )
    assert local.changes.principles[0].description == (
        "State the reason." if detail == DetailLevel.FULL else ""
    )
    assert local.changes.change_notes == original.change_notes
    assert local.changes.delta == original.delta
    rendered = Direction.from_changes(local.changes, "support", detail).render()
    assert rendered == Direction.from_changes(remote.changes, "support", detail).render()
    for item in (*original.change_notes, *original.delta):
        assert item in rendered
    assert control_plane.changes_since(last_seen_version, "support") == original
