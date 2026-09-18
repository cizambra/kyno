"""Local and MCP sources return the same constitution content for the selected detail."""

import pytest

from kyno.sdk.cell import Direction
from kyno.sdk.client import LocalDirectionSource, McpDirectionSource
from kyno.wire.models import DetailLevel


@pytest.mark.parametrize(
    "detail",
    [
        pytest.param(None, id="default-compact"),
        "compact",
        DetailLevel.COMPACT,
        "full",
        DetailLevel.FULL,
    ],
)
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
        constitution_key="support",
    )
    control_plane.apply_direction(
        mission="Resolve support requests",
        declaration="Explain support decisions.",
        principles=[{"title": "Be clear", "description": "State the reason."}],
        change_note="Prioritize resolution",
        constitution_key="support",
    )
    original = control_plane.changes_since(last_seen_version, "support")

    detail_arguments = {} if detail is None else {"detail": detail}
    local = LocalDirectionSource(control_plane).changes_since(
        last_seen_version, constitution_key="support", **detail_arguments
    )
    remote = McpDirectionSource(runner).changes_since(
        last_seen_version, constitution_key="support", **detail_arguments
    )

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
    selected_detail = DetailLevel.COMPACT if detail is None else detail
    rendered = Direction.from_changes(local.changes, "support", selected_detail).render()
    assert rendered == Direction.from_changes(remote.changes, "support", selected_detail).render()
    for item in (*original.change_notes, *original.delta):
        assert item in rendered
    assert control_plane.changes_since(last_seen_version, "support") == original


@pytest.mark.parametrize("detail", [DetailLevel.COMPACT, DetailLevel.FULL])
def test_given_unwritten_direction_when_changes_since_runs_then_both_sources_return_version_zero(
    mcp_runner, detail
):
    runner, control_plane = mcp_runner

    local = LocalDirectionSource(control_plane).changes_since(0, "support", detail)
    remote = McpDirectionSource(runner).changes_since(0, "support", detail)

    assert local.changes == remote.changes
    assert local.changes.current_version == 0
    assert local.changes.changed is False
    assert local.changes.mission == ""
    assert local.changes.declaration == ""
    assert local.changes.principles == ()
    assert local.changes.change_notes == ()
    assert local.changes.delta == ()
    assert local.recording is None


@pytest.mark.parametrize("selection", [{}, {"constitution_key": None}])
def test_given_default_selection_when_direction_sources_pull_then_default_direction_is_returned(
    mcp_runner, selection
):
    runner, control_plane = mcp_runner
    control_plane.apply_direction(mission="Default mission", change_note="Initial")

    local = LocalDirectionSource(control_plane).changes_since(0, **selection)
    remote = McpDirectionSource(runner).changes_since(0, **selection)

    assert local.changes == remote.changes
    assert local.changes.mission == "Default mission"
