"""The SDK connection over the real MCP server."""

from kyno.sdk import DeliveryStatus
from kyno.wire.models import DetailLevel


def test_given_a_connection_when_its_binder_binds_then_the_direction_in_force_serves(
    mcp_connection,
):
    connection, control_plane = mcp_connection
    control_plane.set_direction(mission="M1", change_note="init")
    binder = connection.binder()

    assert "version=1" in binder.bind().render()

    control_plane.set_direction(mission="M2", change_note="pivot")
    assert "version=2" in binder.bind().render()


def test_given_binders_sharing_a_session_when_connection_closes_then_each_uses_its_own_cache(
    mcp_connection,
):
    connection, control_plane = mcp_connection
    control_plane.set_direction(mission="M1", change_note="init")

    first = connection.binder()
    second = connection.binder()
    empty = connection.binder()
    assert first.bind().version == 1
    control_plane.set_direction(mission="M2", change_note="pivot")
    assert second.bind().version == 2

    connection.close()
    first_fallback = first.bind_with_status()
    second_fallback = second.bind_with_status()
    empty_fallback = empty.bind_with_status()
    assert first_fallback.direction.version == 1
    assert second_fallback.direction.version == 2
    assert first_fallback.status is second_fallback.status is DeliveryStatus.CACHED
    assert empty_fallback.status is DeliveryStatus.EMPTY
    assert empty_fallback.direction.version == 0


def test_given_one_connection_when_binders_pull_compact_and_full_then_each_receives_its_projection(
    mcp_connection,
):
    connection, control_plane = mcp_connection
    control_plane.set_direction(
        mission="Help customers", declaration="Explain each decision", change_note="init"
    )
    compact = connection.binder(context=DetailLevel.COMPACT).bind()
    full = connection.binder(context=DetailLevel.FULL).bind()

    assert compact.context is DetailLevel.COMPACT
    assert full.context is DetailLevel.FULL
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
