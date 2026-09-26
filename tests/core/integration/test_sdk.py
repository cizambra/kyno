"""The SDK connection over the real MCP server."""

import pytest

from kyno.sdk import BindingStatus, PullPolicy
from kyno.sdk.errors import KynoUnavailableError
from kyno.wire.models import DetailLevel


def test_given_a_connection_when_its_binder_binds_then_the_direction_in_force_serves(
    mcp_connection,
):
    connection, control_plane = mcp_connection
    control_plane.apply_direction(mission="M1", change_note="init")
    binder = connection.binder()

    assert "version=1" in binder.bind().render()

    control_plane.apply_direction(mission="M2", change_note="pivot")
    assert "version=2" in binder.bind().render()


def test_given_binders_sharing_a_session_when_connection_closes_then_each_uses_its_own_cache(
    mcp_connection,
):
    connection, control_plane = mcp_connection
    control_plane.apply_direction(mission="M1", change_note="init")

    first = connection.binder()
    second = connection.binder()
    empty = connection.binder()
    assert first.bind().version == 1
    control_plane.apply_direction(mission="M2", change_note="pivot")
    assert second.bind().version == 2

    connection.close()
    first_fallback = first.bind_with_status()
    second_fallback = second.bind_with_status()
    empty_fallback = empty.bind_with_status()
    assert first_fallback.direction.version == 1
    assert second_fallback.direction.version == 2
    assert first_fallback.status is second_fallback.status is BindingStatus.CACHED
    assert empty_fallback.status is BindingStatus.EMPTY
    assert empty_fallback.direction.version == 0


def test_given_one_connection_when_binders_pull_compact_and_full_then_each_receives_its_projection(
    mcp_connection,
):
    connection, control_plane = mcp_connection
    control_plane.apply_direction(
        mission="Help customers", declaration="Explain each decision", change_note="init"
    )
    compact = connection.binder(detail=DetailLevel.COMPACT).bind()
    full = connection.binder(detail=DetailLevel.FULL).bind()

    assert compact.detail is DetailLevel.COMPACT
    assert full.detail is DetailLevel.FULL
    assert compact.version == full.version == 1
    assert "Explain each decision" not in compact.render()
    assert "Explain each decision" in full.render()


def test_given_a_closed_connection_when_binding_then_it_degrades_instead_of_crashing(
    mcp_connection,
):
    connection, control_plane = mcp_connection
    binder = connection.binder()
    connection.close()

    direction = binder.bind()
    assert direction.version == 0


@pytest.mark.parametrize("cached", [False, True], ids=["without-cache", "with-cache"])
def test_given_closed_connection_when_fail_closed_bind_with_status_runs_then_unavailable_raises(
    mcp_connection, cached
):
    connection, control_plane = mcp_connection
    control_plane.apply_direction(
        mission="Support customers", change_note="initial", constitution_key="support"
    )
    binder = connection.binder("support", policy=PullPolicy(fail_closed=True))
    if cached:
        assert binder.bind().constitution == "support"
    connection.close()

    with pytest.raises(KynoUnavailableError, match="cannot reach kyno for 'support'"):
        binder.bind_with_status()
