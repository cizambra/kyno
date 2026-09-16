"""The SDK connection over the real MCP server."""

import pytest

from kyno.sdk import DirectionCell
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


def test_given_one_connection_when_making_binders_then_they_share_the_session(mcp_connection):
    connection, control_plane = mcp_connection
    control_plane.set_direction(mission="M1", change_note="init")

    first = connection.binder()
    second = connection.binder()
    assert first.bind().version == 1
    assert second.bind().version == 1

    connection.close()
    # Both degrade together because there is one session under them; the
    # last-known direction keeps serving.
    assert first.bind().version == 1
    assert second.bind().version == 1


@pytest.mark.parametrize("first_context", list(DetailLevel))
def test_given_a_shared_cell_when_connection_requests_another_context_then_setup_is_rejected(
    mcp_connection, first_context
):
    connection, _control_plane = mcp_connection
    cell = DirectionCell()
    connection.binder(cell=cell, context=first_context)
    other_context = (
        DetailLevel.FULL if first_context is DetailLevel.COMPACT else DetailLevel.COMPACT
    )

    with pytest.raises(ValueError, match="separate cell"):
        connection.binder(cell=cell, context=other_context)

    assert cell.names() == ()


def test_given_one_connection_when_contexts_use_separate_cells_then_both_read_requested_direction(
    mcp_connection,
):
    connection, control_plane = mcp_connection
    control_plane.set_direction(
        mission="Help customers", declaration="Explain each decision", change_note="init"
    )
    compact_cell = DirectionCell()
    full_cell = DirectionCell()
    compact = connection.binder(cell=compact_cell, context=DetailLevel.COMPACT).bind()
    full = connection.binder(cell=full_cell, context=DetailLevel.FULL).bind()

    assert compact.context is DetailLevel.COMPACT
    assert full.context is DetailLevel.FULL
    assert compact.version == full.version == 1
    assert compact_cell.get("default") is compact
    assert full_cell.get("default") is full
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
