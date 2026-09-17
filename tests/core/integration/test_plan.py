"""Plans go stale the same way steps do; the tracker is how a planner knows."""


def test_given_support_binder_when_plan_tracker_checks_changes_then_only_support_changes_return(
    mcp_connection,
):
    connection, control_plane = mcp_connection
    control_plane.set_direction(mission="Support", change_note="Initial", constitution="support")
    tracker = connection.binder("support").plan()

    planned = tracker.direction()
    control_plane.set_direction(mission="Sales", change_note="Initial", constitution="sales")
    assert tracker.changed() is None
    control_plane.set_direction(mission="New support", change_note="Update", constitution="support")
    changed = tracker.changed()

    assert planned.constitution == changed.constitution == "support"
    assert changed.version == 2
    assert changed.mission == "New support"


def test_given_a_plan_when_planning_then_the_direction_in_force_is_pulled(mcp_connection):
    conn, control_plane = mcp_connection
    control_plane.set_direction(mission="M1", change_note="init")
    tracker = conn.binder().plan()

    assert tracker.direction().version == 1


def test_given_an_unchanged_direction_when_checking_then_no_replan_is_needed(mcp_connection):
    conn, control_plane = mcp_connection
    control_plane.set_direction(mission="M1", change_note="init")
    tracker = conn.binder().plan()
    tracker.direction()

    assert tracker.changed() is None


def test_given_a_new_version_mid_run_when_checking_then_the_fresh_direction_comes_back(
    mcp_connection,
):
    conn, control_plane = mcp_connection
    control_plane.set_direction(mission="M1", change_note="init")
    tracker = conn.binder().plan()
    tracker.direction()

    control_plane.set_direction(mission="M2", change_note="pivot")
    fresh = tracker.changed()
    assert fresh is not None
    assert fresh.version == 2
    assert "M2" in fresh.render()


def test_given_a_replan_when_it_is_applied_then_the_tracker_arms_against_the_new_version(
    mcp_connection,
):
    conn, control_plane = mcp_connection
    control_plane.set_direction(mission="M1", change_note="init")
    tracker = conn.binder().plan()
    tracker.direction()
    control_plane.set_direction(mission="M2", change_note="pivot")

    assert tracker.changed() is not None
    # The orchestrator re-plans against the fresh direction, which is a new
    # plan pull; from then on the plan is current again.
    assert tracker.direction().version == 2
    assert tracker.changed() is None


def test_given_no_direction_yet_when_planning_then_version_zero_holds_and_the_first_replans(
    mcp_connection,
):
    conn, control_plane = mcp_connection
    tracker = conn.binder().plan()

    assert tracker.direction().version == 0
    control_plane.set_direction(mission="M1", change_note="init")
    fresh = tracker.changed()
    assert fresh is not None
    assert fresh.version == 1


def test_given_an_unreachable_plane_when_checking_then_no_change_is_reported(mcp_connection):
    conn, control_plane = mcp_connection
    control_plane.set_direction(mission="M1", change_note="init")
    tracker = conn.binder().plan()
    tracker.direction()
    conn.close()

    # The pull degrades to the last-known direction, which is the planned
    # one, so there is nothing to replan against.
    assert tracker.changed() is None


class RegressingSource:
    """A control plane behind a load balancer where one replica lags: the
    first pull answers version 2, later pulls answer version 1."""

    def __init__(self):
        self.calls = 0

    def changes_since(self, last_seen_version, constitution, detail="compact"):
        from kyno.sdk.client import DirectionResponse
        from kyno.wire.models import ChangesSince

        self.calls += 1
        version = 2 if self.calls == 1 else 1
        changes = ChangesSince(
            current_version=version,
            changed=True,
            mission=f"M{version}",
            principles=(),
            change_notes=(f"note {version}",),
            changed_mission=True,
            changed_principles=False,
        )
        return DirectionResponse(changes)


def test_given_a_replica_serving_an_older_version_when_checking_then_the_plan_never_rolls_back():
    from kyno.sdk import DirectionBinder

    binder = DirectionBinder(RegressingSource())
    tracker = binder.plan()
    assert tracker.direction().version == 2

    # The stale replica answers version 1; the cell refuses to go backwards,
    # so the bind serves the held version 2 and the plan is not disturbed.
    assert binder.bind().version == 2
    assert tracker.changed() is None
