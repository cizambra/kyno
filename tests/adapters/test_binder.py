import pytest

from kyno.errors import KynoUnavailableError, UnknownVersionError
from kyno.sdk.binder import DirectionBinder
from kyno.sdk.cell import COMPACT, FULL, Direction, DirectionCell
from kyno.sdk.client import LocalDirectionSource
from kyno.sdk.policy import (
    PULL_FAILED_EMPTY,
    PULL_FAILED_STALE,
    PullPolicy,
    RecordingSink,
)


def test_given_a_step_when_binding_then_the_current_version_is_bound(control_plane):
    control_plane.set_direction(mission="M1", change_note="init")
    binder = DirectionBinder(LocalDirectionSource(control_plane))

    direction = binder.bind()
    assert direction.version == 1 and direction.mission == "M1"
    assert direction.constitution == "default"


def test_given_a_direction_change_between_steps_when_binding_the_second_then_it_sees_the_change(
    control_plane,
):
    control_plane.set_direction(mission="M1", change_note="init")
    binder = DirectionBinder(LocalDirectionSource(control_plane))
    first = binder.bind()

    control_plane.set_direction(mission="M2", change_note="pivot")
    second = binder.bind()

    assert (first.version, first.mission) == (1, "M1")
    assert (second.version, second.mission) == (2, "M2")


def test_given_a_bound_step_when_the_next_pull_asks_then_the_known_version_has_advanced(
    control_plane, scripted_source
):
    scripted_source.set("default", 4, "M4")
    binder = DirectionBinder(scripted_source)

    binder.bind()
    scripted_source.set("default", 5, "M5")
    binder.bind()

    assert scripted_source.calls == [(0, "default"), (4, "default")]


def test_given_bindings_to_different_constitutions_when_binding_then_they_do_not_collide(
    scripted_source,
):
    scripted_source.set("eu", 2, "EU")
    scripted_source.set("us", 9, "US")
    binder = DirectionBinder(scripted_source)

    assert binder.bind("eu").mission == "EU"
    assert binder.bind("us").mission == "US"
    assert binder.cell.known_version("eu") == 2
    assert binder.cell.known_version("us") == 9


def test_given_a_pull_failure_when_binding_then_the_last_known_direction_serves(scripted_source):
    scripted_source.set("default", 3, "M3")
    sink = RecordingSink()
    binder = DirectionBinder(scripted_source, telemetry=sink)
    binder.bind()

    scripted_source.failure = OSError("connection refused")
    direction = binder.bind()

    assert direction.version == 3 and direction.mission == "M3"
    assert [e.kind for e in sink.events] == [PULL_FAILED_STALE]


def test_given_a_pull_failure_and_an_empty_cell_when_binding_then_the_empty_direction_serves(
    scripted_source,
):
    scripted_source.failure = OSError("connection refused")
    sink = RecordingSink()
    binder = DirectionBinder(scripted_source, telemetry=sink)

    direction = binder.bind("eu")

    assert direction.version == 0 and direction.constitution == "eu"
    assert [e.kind for e in sink.events] == [PULL_FAILED_EMPTY]


def test_given_a_fail_closed_policy_when_a_pull_fails_then_it_raises_instead_of_degrading(
    scripted_source,
):
    scripted_source.failure = OSError("connection refused")
    binder = DirectionBinder(scripted_source, policy=PullPolicy(fail_closed=True))

    with pytest.raises(KynoUnavailableError):
        binder.bind()


def test_given_a_subscriber_when_sharing_the_cell_then_both_see_the_same_direction(scripted_source):
    cell = DirectionCell()
    scripted_source.set("default", 2, "M2")
    binder = DirectionBinder(scripted_source, cell=cell)

    binder.bind()

    assert cell.get("default").version == 2 and binder.cell is cell


def test_given_a_fail_closed_policy_when_a_last_direction_exists_then_it_still_refuses(
    scripted_source,
):
    scripted_source.set("default", 3, "M3")
    binder = DirectionBinder(scripted_source, policy=PullPolicy(fail_closed=True))
    binder.bind()

    scripted_source.failure = OSError("connection refused")
    with pytest.raises(KynoUnavailableError):
        binder.bind()


def test_given_a_kyno_error_when_binding_then_it_degrades_like_an_unreachable_kyno(scripted_source):
    scripted_source.set("default", 3, "M3")
    sink = RecordingSink()
    binder = DirectionBinder(scripted_source, telemetry=sink)
    binder.bind()

    scripted_source.failure = UnknownVersionError("known_version 3 > current 1")
    direction = binder.bind()

    assert direction.version == 3
    assert [e.kind for e in sink.events] == [PULL_FAILED_STALE]


def test_given_an_unexpected_error_when_binding_then_it_is_not_swallowed(scripted_source):
    """Degrading on everything would hide adapter bugs as silent staleness."""
    scripted_source.failure = ValueError("bad wiring")
    binder = DirectionBinder(scripted_source)

    with pytest.raises(ValueError):
        binder.bind()


def test_given_a_degraded_bind_when_reading_the_event_then_the_reason_and_version_are_there(
    scripted_source,
):
    scripted_source.set("eu", 7, "EU")
    sink = RecordingSink()
    binder = DirectionBinder(scripted_source, telemetry=sink)
    binder.bind("eu")

    scripted_source.failure = OSError("connection refused")
    binder.bind("eu")

    event = sink.events[0]
    assert (event.constitution, event.version) == ("eu", 7)
    assert "connection refused" in event.detail


def test_given_a_stale_reply_when_binding_then_the_bound_direction_does_not_roll_back(
    scripted_source,
):
    """A push and a pull race by design, so an older reply must lose."""
    scripted_source.set("default", 5, "M5")
    binder = DirectionBinder(scripted_source)
    binder.bind()

    scripted_source.set("default", 4, "M4")
    direction = binder.bind()

    assert (direction.version, direction.mission) == (5, "M5")


def test_given_a_binder_with_no_sink_when_a_pull_fails_then_it_degrades_quietly(scripted_source):
    """The default sink logs; a host that passes nothing must not crash."""
    scripted_source.failure = OSError("connection refused")

    assert DirectionBinder(scripted_source).bind() == Direction.empty("default")


def test_given_a_binder_when_binding_any_direction_then_its_context_is_stamped_on_it(
    scripted_source,
):
    scripted_source.set("eu", 2, "EU")
    binder = DirectionBinder(scripted_source, context=FULL)
    assert binder.bind("eu").context == FULL


def test_given_a_degraded_bind_when_reading_the_empty_direction_then_the_context_is_stamped(
    scripted_source,
):
    scripted_source.failure = OSError("connection refused")
    binder = DirectionBinder(scripted_source, context=FULL, policy=PullPolicy())
    assert binder.bind("eu").context == FULL


def test_given_no_context_asked_when_binding_then_the_compact_context_is_used(scripted_source):
    scripted_source.set("eu", 2, "EU")
    assert DirectionBinder(scripted_source).bind("eu").context == COMPACT


def test_given_an_unknown_context_when_building_the_binder_then_it_is_refused(scripted_source):
    # At wiring time, not at the first step: a typo must not survive until a
    # crew is already running.
    with pytest.raises(ValueError, match="verbose"):
        DirectionBinder(scripted_source, context="verbose")


def test_given_a_context_choice_when_binding_then_only_the_injected_block_changes(control_plane):
    # The knob is about what an agent is sent at every step, never about what
    # the control plane holds or answers.
    control_plane.set_direction(
        mission="M1",
        declaration="The long form.",
        principles=({"title": "Be honest", "description": "Say the hard number first."},),
        change_note="init",
    )
    source = LocalDirectionSource(control_plane)
    compact = DirectionBinder(source).bind()
    full = DirectionBinder(source, context=FULL).bind()

    assert "The long form." not in compact.render()
    assert "The long form." in full.render()
    assert compact.declaration == full.declaration == "The long form."
    assert compact.principles == full.principles


def test_given_a_compact_binding_when_pulling_then_kyno_is_asked_for_the_compact_form(
    scripted_source,
):
    # Do not fetch what you will not inject: the pull matches the binding.
    scripted_source.set("eu", 2, "EU")
    DirectionBinder(scripted_source).bind("eu")
    DirectionBinder(scripted_source, context=FULL).bind("eu")
    assert scripted_source.details == [COMPACT, FULL]
