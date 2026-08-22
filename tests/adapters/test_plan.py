"""Plans go stale the same way steps do; the tracker is how a planner knows."""

from contextlib import asynccontextmanager

import pytest

from kyno.mcp_server import build_server
from kyno.sdk import KynoConnection, SessionRunner
from kyno.service import ControlPlane
from kyno.store.sql import SqlConstitutionStore


@pytest.fixture
def connection():
    store = SqlConstitutionStore(url="sqlite://")
    store.create_all()
    control_plane = ControlPlane(store)
    server = build_server(control_plane)

    @asynccontextmanager
    async def session_factory(message_handler=None):
        from mcp.shared.memory import create_connected_server_and_client_session

        async with create_connected_server_and_client_session(
            server, message_handler=message_handler
        ) as session:
            yield session

    runner = SessionRunner(session_factory)
    runner.start()
    connection = KynoConnection(runner)
    try:
        yield connection, control_plane
    finally:
        connection.close()


def test_planning_pulls_the_direction_in_force(connection):
    conn, control_plane = connection
    control_plane.set_direction(mission="M1", change_note="init")
    tracker = conn.binder().plan()

    assert tracker.direction().version == 1


def test_an_unchanged_direction_needs_no_replan(connection):
    conn, control_plane = connection
    control_plane.set_direction(mission="M1", change_note="init")
    tracker = conn.binder().plan()
    tracker.direction()

    assert tracker.changed() is None


def test_a_new_version_mid_run_hands_back_the_fresh_direction(connection):
    conn, control_plane = connection
    control_plane.set_direction(mission="M1", change_note="init")
    tracker = conn.binder().plan()
    tracker.direction()

    control_plane.set_direction(mission="M2", change_note="pivot")
    fresh = tracker.changed()
    assert fresh is not None
    assert fresh.version == 2
    assert "M2" in fresh.render()


def test_replanning_arms_the_tracker_against_the_new_version(connection):
    conn, control_plane = connection
    control_plane.set_direction(mission="M1", change_note="init")
    tracker = conn.binder().plan()
    tracker.direction()
    control_plane.set_direction(mission="M2", change_note="pivot")

    assert tracker.changed() is not None
    # The orchestrator re-plans against the fresh direction, which is a new
    # plan pull; from then on the plan is current again.
    assert tracker.direction().version == 2
    assert tracker.changed() is None


def test_a_plan_before_any_direction_is_version_zero_and_replans_on_the_first(connection):
    conn, control_plane = connection
    tracker = conn.binder().plan()

    assert tracker.direction().version == 0
    control_plane.set_direction(mission="M1", change_note="init")
    fresh = tracker.changed()
    assert fresh is not None
    assert fresh.version == 1


def test_an_unreachable_plane_reports_no_change(connection):
    conn, control_plane = connection
    control_plane.set_direction(mission="M1", change_note="init")
    tracker = conn.binder().plan()
    tracker.direction()
    conn.close()

    # The pull degrades to the last-known direction, which is the planned
    # one, so there is nothing to replan against.
    assert tracker.changed() is None
