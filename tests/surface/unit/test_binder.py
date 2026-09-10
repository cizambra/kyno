from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace

import pytest

from kyno.errors import UnknownVersionError
from kyno.sdk.binder import DirectionBinder
from kyno.sdk.binding import DeliveryStatus
from kyno.sdk.cell import Direction, DirectionCell
from kyno.sdk.errors import KynoUnavailableError
from kyno.sdk.policy import PullPolicy
from kyno.sdk.telemetry import (
    EventType,
    RecordingSink,
)
from kyno.wire.models import DetailLevel


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
    assert [event.kind for event in sink.events] == [EventType.PULL_FAILED_STALE]


def test_given_a_pull_failure_and_an_empty_cell_when_binding_then_the_empty_direction_serves(
    scripted_source,
):
    scripted_source.failure = OSError("connection refused")
    sink = RecordingSink()
    binder = DirectionBinder(scripted_source, telemetry=sink)

    direction = binder.bind("eu")

    assert direction.version == 0 and direction.constitution == "eu"
    assert [event.kind for event in sink.events] == [EventType.PULL_FAILED_EMPTY]


def test_given_a_fail_closed_policy_when_a_pull_fails_then_it_raises_instead_of_degrading(
    scripted_source,
):
    scripted_source.failure = OSError("connection refused")
    binder = DirectionBinder(scripted_source, policy=PullPolicy(fail_closed=True))

    with pytest.raises(KynoUnavailableError):
        binder.bind()


def test_given_a_shared_cell_when_binding_then_the_binder_and_caller_see_the_same_direction(
    scripted_source,
):
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
    assert [event.kind for event in sink.events] == [EventType.PULL_FAILED_STALE]


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
    """Overlapping pulls can finish out of order, so an older reply must lose."""
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
    binder = DirectionBinder(scripted_source, context=DetailLevel.FULL)
    assert binder.bind("eu").context is DetailLevel.FULL


def test_given_a_degraded_bind_when_reading_the_empty_direction_then_the_context_is_stamped(
    scripted_source,
):
    scripted_source.failure = OSError("connection refused")
    binder = DirectionBinder(scripted_source, context=DetailLevel.FULL, policy=PullPolicy())
    assert binder.bind("eu").context is DetailLevel.FULL


def test_given_no_context_asked_when_binding_then_the_compact_context_is_used(scripted_source):
    scripted_source.set("eu", 2, "EU")
    assert DirectionBinder(scripted_source).bind("eu").context is DetailLevel.COMPACT


def test_given_an_unknown_context_when_building_the_binder_then_it_is_refused(scripted_source):
    # At wiring time, not at the first step: a typo must not survive until a
    # crew is already running.
    with pytest.raises(ValueError, match="verbose"):
        DirectionBinder(scripted_source, context="verbose")


def test_given_a_compact_binding_when_pulling_then_kyno_is_asked_for_the_compact_form(
    scripted_source,
):
    # Do not fetch what you will not inject: the pull matches the binding.
    scripted_source.set("eu", 2, "EU")
    DirectionBinder(scripted_source).bind("eu")
    DirectionBinder(scripted_source, context=DetailLevel.FULL).bind("eu")
    assert scripted_source.details == [DetailLevel.COMPACT, DetailLevel.FULL]


@pytest.mark.parametrize("version", [0, 3])
def test_given_an_authoritative_reply_when_binding_with_status_then_it_is_current(
    scripted_source, version
):
    scripted_source.set("sales", version, "Mission" if version else "")
    binder = DirectionBinder(scripted_source)
    binding = binder.bind_with_status("sales")
    assert binding.status is DeliveryStatus.CURRENT
    assert binding.direction.version == version
    assert binding.direction.constitution == "sales"
    assert scripted_source.calls == [(0, "sales")]


@pytest.mark.parametrize("version", [0, 3])
@pytest.mark.parametrize("failure", [OSError("offline"), UnknownVersionError("unknown")])
def test_given_a_cached_version_when_the_pull_fails_then_the_binding_is_cached(
    scripted_source, version, failure
):
    scripted_source.set("sales", version, "Mission" if version else "")
    binder = DirectionBinder(scripted_source)
    first = binder.bind_with_status("sales")
    scripted_source.failure = failure
    fallback = binder.bind_with_status("sales")
    assert fallback.status is DeliveryStatus.CACHED
    assert fallback.direction is first.direction
    assert first.status is DeliveryStatus.CURRENT


def test_given_no_cached_direction_when_the_pull_fails_then_the_binding_is_empty(scripted_source):
    scripted_source.failure = OSError("offline")
    binder = DirectionBinder(scripted_source, context=DetailLevel.FULL)
    binding = binder.bind_with_status("sales")
    assert binding.status is DeliveryStatus.EMPTY
    assert binding.direction == Direction.empty("sales", DetailLevel.FULL)


@pytest.mark.parametrize("cached", [False, True])
def test_given_fail_closed_when_binding_with_status_fails_then_it_raises(scripted_source, cached):
    binder = DirectionBinder(scripted_source, policy=PullPolicy(fail_closed=True))
    if cached:
        scripted_source.set("sales", 2, "Mission")
        binder.bind_with_status("sales")
    scripted_source.failure = OSError("offline")
    with pytest.raises(KynoUnavailableError):
        binder.bind_with_status("sales")


def test_given_an_unexpected_error_when_binding_with_status_then_it_propagates(scripted_source):
    scripted_source.failure = ValueError("bad wiring")
    with pytest.raises(ValueError, match="bad wiring"):
        DirectionBinder(scripted_source).bind_with_status()


@pytest.mark.parametrize("cached", [False, True])
def test_given_a_failed_pull_when_the_source_recovers_then_a_new_binding_is_current(
    scripted_source, cached
):
    binder = DirectionBinder(scripted_source)
    if cached:
        scripted_source.set("sales", 1, "Old")
        binder.bind_with_status("sales")
    scripted_source.failure = OSError("offline")
    fallback = binder.bind_with_status("sales")
    scripted_source.failure = None
    scripted_source.set("sales", 2, "New")
    recovered = binder.bind_with_status("sales")
    assert recovered.status is DeliveryStatus.CURRENT
    assert recovered.direction.version == 2
    assert fallback.status is (DeliveryStatus.CACHED if cached else DeliveryStatus.EMPTY)


def test_given_one_cached_constitution_when_another_pull_fails_then_it_has_no_fallback(
    scripted_source,
):
    binder = DirectionBinder(scripted_source)
    scripted_source.set("sales", 3, "Sales")
    binder.bind_with_status("sales")
    scripted_source.failure = OSError("offline")
    assert binder.bind_with_status("sales").status is DeliveryStatus.CACHED
    support = binder.bind_with_status("support")
    assert support.status is DeliveryStatus.EMPTY
    assert support.direction.constitution == "support"


def test_given_an_older_reply_when_the_cell_holds_newer_direction_then_the_binding_is_cached(
    scripted_source,
):
    scripted_source.set("sales", 5, "New")
    binder = DirectionBinder(scripted_source)
    first = binder.bind_with_status("sales")
    scripted_source.set("sales", 4, "Old")
    retained = binder.bind_with_status("sales")
    assert retained.direction is first.direction
    assert retained.status is DeliveryStatus.CACHED
    assert first.status is DeliveryStatus.CURRENT


def test_given_bind_without_status_when_pulling_then_it_returns_direction_with_one_request(
    scripted_source,
):
    scripted_source.set("sales", 2, "Sales")
    direction = DirectionBinder(scripted_source).bind("sales")
    assert isinstance(direction, Direction)
    assert direction.version == 2
    assert scripted_source.calls == [(0, "sales")]


def test_given_overlapping_pulls_when_the_older_reply_finishes_last_then_it_returns_cached(
    scripted_source,
):
    scripted_source.set("sales", 4, "Old")
    old_reply = scripted_source.replies["sales"]
    started = Event()
    release = Event()
    cell = DirectionCell()

    def delayed_changes(known_version, constitution, context):
        started.set()
        assert release.wait(timeout=10)
        return old_reply

    slower = DirectionBinder(SimpleNamespace(changes_since=delayed_changes), cell=cell)
    faster = DirectionBinder(scripted_source, cell=cell)
    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(slower.bind_with_status, "sales")
        try:
            assert started.wait(timeout=10)
            scripted_source.set("sales", 5, "New")
            current = faster.bind_with_status("sales")
        finally:
            release.set()
        retained = pending.result(timeout=10)

    assert current.status is DeliveryStatus.CURRENT
    assert retained.status is DeliveryStatus.CACHED
    assert retained.direction is current.direction
    assert retained.direction.version == cell.known_version("sales") == 5
