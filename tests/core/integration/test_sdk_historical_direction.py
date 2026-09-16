"""SDK historical reads return exact full versions without changing live binder state."""

from kyno.wire.models import DetailLevel


def test_given_newer_direction_when_reading_an_old_version_then_original_full_content_returns(
    mcp_connection,
):
    connection, control_plane = mcp_connection
    control_plane.set_direction(
        mission="Original mission",
        declaration="Original declaration",
        principles=[{"title": "Honesty", "description": "State the facts."}],
        change_note="Initial version",
        constitution="example",
    )
    control_plane.set_direction(
        mission="New mission", change_note="Updated", constitution="example"
    )
    binder = connection.binder(context="full")
    assert binder.bind("example").version == 2
    historical = connection.get_direction_version(1, "example")
    assert historical.constitution == "example"
    assert historical.version == 1
    assert historical.mission == "Original mission"
    assert historical.declaration == "Original declaration"
    assert historical.principles[0].description == "State the facts."
    assert historical.context is DetailLevel.FULL
    assert historical.delta == ()
    assert historical.change_notes == ()
    assert binder.bind("example").version == 2


def test_given_missing_version_when_reading_history_then_no_current_direction_is_substituted(
    mcp_connection,
):
    connection, control_plane = mcp_connection
    control_plane.set_direction(mission="Current", change_note="Initial version")
    assert connection.get_direction_version(2) is None
    assert connection.get_direction_version(1, "unknown") is None


def test_given_live_direction_when_reading_version_zero_then_empty_state_returns(mcp_connection):
    connection, control_plane = mcp_connection
    control_plane.set_direction(mission="Current", change_note="Initial version")
    direction = connection.get_direction_version(0)
    assert direction.version == 0
    assert direction.mission == ""
