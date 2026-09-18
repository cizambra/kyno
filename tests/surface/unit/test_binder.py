import logging
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace

import pytest

from kyno.errors import UnknownVersionError
from kyno.sdk.binder import DirectionBinder
from kyno.sdk.binding import BindingStatus
from kyno.sdk.cell import Direction
from kyno.sdk.client import DirectionResponse
from kyno.sdk.errors import KynoUnavailableError
from kyno.sdk.policy import PullPolicy
from kyno.sdk.recording import RecordingReceipt
from kyno.wire.delivery import RecordingStatus
from kyno.wire.models import DetailLevel


@pytest.mark.parametrize("context", list(DetailLevel))
@pytest.mark.parametrize("populated", [False, True], ids=["before-pull", "after-pull"])
def test_given_fixed_context_when_assigning_binder_context_then_attribute_error_preserves_pulls(
    scripted_source, context, populated
):
    scripted_source.set("default", 1, "Support customers")
    binder = DirectionBinder(scripted_source, context=context.value)
    if populated:
        binder.bind()
    other_context = DetailLevel.FULL if context is DetailLevel.COMPACT else DetailLevel.COMPACT

    with pytest.raises(AttributeError):
        binder.context = other_context

    assert binder.context is context
    assert binder.bind().context is context
    assert all(detail is context for detail in scripted_source.details)


@pytest.mark.parametrize("constitution_name", [None, 1, True, [], {}])
def test_given_non_string_constitution_name_when_creating_direction_binder_then_raises_type_error(
    scripted_source, constitution_name
):
    with pytest.raises(TypeError, match="constitution name must be a string"):
        DirectionBinder(scripted_source, constitution_name)
    assert scripted_source.calls == []


def test_given_support_binder_when_bind_runs_then_every_pull_uses_support(scripted_source):
    scripted_source.set("support", 3, "Help customers")
    binder = DirectionBinder(scripted_source, "support")

    assert binder.constitution == "support"
    assert binder.bind().constitution == "support"
    assert binder.bind_with_status().direction.constitution == "support"
    assert scripted_source.calls == [(0, "support"), (3, "support")]


def test_given_support_binder_when_assigning_constitution_then_attribute_error_keeps_support(
    scripted_source,
):
    scripted_source.set("support", 3, "Help customers")
    binder = DirectionBinder(scripted_source, "support")

    with pytest.raises(AttributeError):
        binder.constitution = "sales"

    assert binder.constitution == "support"
    assert binder.bind().constitution == "support"
    assert scripted_source.calls == [(0, "support")]


def test_given_a_bound_step_when_the_next_pull_asks_then_the_last_seen_version_has_advanced(
    control_plane, scripted_source
):
    scripted_source.set("default", 4, "M4")
    binder = DirectionBinder(scripted_source)

    binder.bind()
    scripted_source.set("default", 5, "M5")
    binder.bind()

    assert scripted_source.calls == [(0, "default"), (4, "default")]


def test_given_constitution_bound_binders_when_bind_runs_then_last_seen_versions_are_independent(
    scripted_source,
):
    scripted_source.set("eu", 2, "EU")
    scripted_source.set("us", 9, "US")
    european = DirectionBinder(scripted_source, "eu")
    american = DirectionBinder(scripted_source, "us")

    assert european.bind().mission == "EU"
    assert american.bind().mission == "US"
    european.bind()
    american.bind()
    assert scripted_source.calls == [(0, "eu"), (0, "us"), (2, "eu"), (9, "us")]


@pytest.mark.parametrize("version", [0, 3], ids=["unwritten-constitution", "written-direction"])
def test_given_cached_direction_when_bind_fails_then_warning_reports_cached_fallback_and_version(
    scripted_source, caplog, version
):
    mission = "M3" if version else ""
    scripted_source.set("default", version, mission)
    binder = DirectionBinder(scripted_source)
    binder.bind()

    scripted_source.failure = OSError("connection refused")
    direction = binder.bind()

    assert direction.version == version and direction.mission == mission
    assert caplog.record_tuples == [
        (
            "kyno.sdk.binder",
            logging.WARNING,
            f"kyno pull_failed_cached constitution=default version={version} connection refused",
        )
    ]


def test_given_a_pull_failure_and_an_empty_cell_when_binding_then_the_empty_direction_serves(
    scripted_source,
    caplog,
):
    scripted_source.failure = OSError("connection refused")
    binder = DirectionBinder(scripted_source, "eu")

    direction = binder.bind()

    assert direction.version == 0 and direction.constitution == "eu"
    assert caplog.record_tuples == [
        (
            "kyno.sdk.binder",
            logging.WARNING,
            "kyno pull_failed_empty constitution=eu version=0 connection refused",
        )
    ]


def test_given_a_fail_closed_policy_when_a_pull_fails_then_it_raises_instead_of_degrading(
    scripted_source,
    caplog,
):
    scripted_source.failure = OSError("connection refused")
    binder = DirectionBinder(scripted_source, policy=PullPolicy(fail_closed=True))

    with pytest.raises(KynoUnavailableError):
        binder.bind()

    assert caplog.record_tuples == []


def test_given_current_direction_when_bind_with_status_succeeds_then_no_fallback_warning_is_logged(
    scripted_source,
    caplog,
):
    scripted_source.set("default", 3, "M3")

    binding = DirectionBinder(scripted_source).bind_with_status()

    assert binding.status is BindingStatus.PULLED
    assert caplog.record_tuples == []


def test_given_error_log_level_when_bind_with_status_falls_back_then_warning_is_filtered(
    scripted_source,
    caplog,
):
    scripted_source.failure = OSError("connection refused")
    binder = DirectionBinder(scripted_source)

    with caplog.at_level(logging.ERROR, logger="kyno.sdk.binder"):
        binding = binder.bind_with_status()

    assert binding.status is BindingStatus.EMPTY
    assert caplog.record_tuples == []


def test_given_application_logging_when_bind_falls_back_then_handlers_and_levels_stay_unchanged(
    scripted_source,
):
    root_logger = logging.getLogger()
    binder_logger = logging.getLogger("kyno.sdk.binder")
    root_settings = (root_logger.level, tuple(root_logger.handlers))
    binder_settings = (binder_logger.level, tuple(binder_logger.handlers), binder_logger.propagate)
    scripted_source.failure = OSError("connection refused")

    DirectionBinder(scripted_source).bind()

    assert (root_logger.level, tuple(root_logger.handlers)) == root_settings
    assert (
        binder_logger.level,
        tuple(binder_logger.handlers),
        binder_logger.propagate,
    ) == binder_settings


def test_given_binders_when_bind_with_status_fails_then_logs_name_each_constitution_and_fallback(
    scripted_source, caplog
):
    scripted_source.set("support", 3, "Help customers")
    support = DirectionBinder(scripted_source, "support")
    sales = DirectionBinder(scripted_source, "sales")
    support.bind()
    scripted_source.failure = OSError("connection refused")

    support_binding = support.bind_with_status()
    sales_binding = sales.bind_with_status()

    assert support_binding.status is BindingStatus.CACHED
    assert sales_binding.status is BindingStatus.EMPTY
    records = [record for record in caplog.records if record.name == "kyno.sdk.binder"]
    assert [record.levelno for record in records] == [logging.WARNING, logging.WARNING]
    assert [record.getMessage() for record in records] == [
        "kyno pull_failed_cached constitution=support version=3 connection refused",
        "kyno pull_failed_empty constitution=sales version=0 connection refused",
    ]


def test_given_one_binder_has_pulled_when_another_calls_bind_then_it_sends_last_seen_version_zero(
    scripted_source,
):
    scripted_source.set("default", 2, "M2")
    first = DirectionBinder(scripted_source)
    second = DirectionBinder(scripted_source)

    first.bind()
    second.bind()

    assert scripted_source.calls == [(0, "default"), (0, "default")]


def test_given_a_fail_closed_policy_when_a_last_direction_exists_then_it_still_refuses(
    scripted_source,
):
    scripted_source.set("default", 3, "M3")
    binder = DirectionBinder(scripted_source, policy=PullPolicy(fail_closed=True))
    binder.bind()

    scripted_source.failure = OSError("connection refused")
    with pytest.raises(KynoUnavailableError):
        binder.bind()


def test_given_a_kyno_error_when_binding_then_it_degrades_like_an_unreachable_kyno(
    scripted_source, caplog
):
    scripted_source.set("default", 3, "M3")
    binder = DirectionBinder(scripted_source)
    binder.bind()

    scripted_source.failure = UnknownVersionError("last_seen_version 3 > current 1")
    direction = binder.bind()

    assert direction.version == 3
    assert "pull_failed_cached" in caplog.text


def test_given_an_unexpected_error_when_binding_then_it_is_not_swallowed(scripted_source):
    """Degrading on everything would hide adapter bugs as silent staleness."""
    scripted_source.failure = ValueError("bad wiring")
    binder = DirectionBinder(scripted_source)

    with pytest.raises(ValueError):
        binder.bind()


def test_given_cached_direction_when_bind_fails_then_warning_names_constitution_version_and_reason(
    scripted_source,
    caplog,
):
    scripted_source.set("eu", 7, "EU")
    binder = DirectionBinder(scripted_source, "eu")
    binder.bind()

    scripted_source.failure = OSError("connection refused")
    binder.bind()

    assert caplog.record_tuples == [
        (
            "kyno.sdk.binder",
            logging.WARNING,
            "kyno pull_failed_cached constitution=eu version=7 connection refused",
        )
    ]


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
    binder = DirectionBinder(scripted_source, "eu", context=DetailLevel.FULL)
    assert binder.bind().context is DetailLevel.FULL


def test_given_a_degraded_bind_when_reading_the_empty_direction_then_the_context_is_stamped(
    scripted_source,
):
    scripted_source.failure = OSError("connection refused")
    binder = DirectionBinder(scripted_source, "eu", context=DetailLevel.FULL, policy=PullPolicy())
    assert binder.bind().context is DetailLevel.FULL


def test_given_no_context_asked_when_binding_then_the_compact_context_is_used(scripted_source):
    scripted_source.set("eu", 2, "EU")
    assert DirectionBinder(scripted_source, "eu").bind().context is DetailLevel.COMPACT


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
    DirectionBinder(scripted_source, "eu").bind()
    DirectionBinder(scripted_source, "eu", context=DetailLevel.FULL).bind()
    assert scripted_source.details == [DetailLevel.COMPACT, DetailLevel.FULL]


@pytest.mark.parametrize("version", [0, 3])
def test_given_an_authoritative_reply_when_binding_with_status_then_it_is_pulled(
    scripted_source, version
):
    scripted_source.set("sales", version, "Mission" if version else "")
    binder = DirectionBinder(scripted_source, "sales")
    binding = binder.bind_with_status()
    assert binding.status == "pulled"
    assert binding.direction.version == version
    assert binding.direction.constitution == "sales"
    assert scripted_source.calls == [(0, "sales")]


@pytest.mark.parametrize("version", [0, 3])
@pytest.mark.parametrize("failure", [OSError("offline"), UnknownVersionError("unknown")])
def test_given_a_cached_version_when_the_pull_fails_then_the_binding_is_cached(
    scripted_source, version, failure
):
    scripted_source.set("sales", version, "Mission" if version else "")
    binder = DirectionBinder(scripted_source, "sales")
    first = binder.bind_with_status()
    scripted_source.failure = failure
    fallback = binder.bind_with_status()
    assert fallback.status is BindingStatus.CACHED
    assert fallback.direction is first.direction
    assert first.status is BindingStatus.PULLED


def test_given_no_cached_direction_when_the_pull_fails_then_the_binding_is_empty(scripted_source):
    scripted_source.failure = OSError("offline")
    binder = DirectionBinder(scripted_source, "sales", context=DetailLevel.FULL)
    binding = binder.bind_with_status()
    assert binding.status is BindingStatus.EMPTY
    assert binding.direction == Direction.empty("sales", DetailLevel.FULL)


@pytest.mark.parametrize("cached", [False, True])
def test_given_fail_closed_when_binding_with_status_fails_then_it_raises(scripted_source, cached):
    binder = DirectionBinder(scripted_source, "sales", policy=PullPolicy(fail_closed=True))
    if cached:
        scripted_source.set("sales", 2, "Mission")
        binder.bind_with_status()
    scripted_source.failure = OSError("offline")
    with pytest.raises(KynoUnavailableError):
        binder.bind_with_status()


def test_given_an_unexpected_error_when_binding_with_status_then_it_propagates(scripted_source):
    scripted_source.failure = ValueError("bad wiring")
    with pytest.raises(ValueError, match="bad wiring"):
        DirectionBinder(scripted_source).bind_with_status()


@pytest.mark.parametrize("cached", [False, True])
def test_given_a_failed_pull_when_the_source_recovers_then_a_new_binding_is_pulled(
    scripted_source, cached
):
    binder = DirectionBinder(scripted_source, "sales")
    if cached:
        scripted_source.set("sales", 1, "Old")
        binder.bind_with_status()
    scripted_source.failure = OSError("offline")
    fallback = binder.bind_with_status()
    scripted_source.failure = None
    scripted_source.set("sales", 2, "New")
    recovered = binder.bind_with_status()
    assert recovered.status is BindingStatus.PULLED
    assert recovered.direction.version == 2
    assert fallback.status is (BindingStatus.CACHED if cached else BindingStatus.EMPTY)


def test_given_only_sales_cached_when_support_pull_fails_then_support_binding_is_empty(
    scripted_source,
):
    sales = DirectionBinder(scripted_source, "sales")
    support_binder = DirectionBinder(scripted_source, "support")
    scripted_source.set("sales", 3, "Sales")
    sales.bind_with_status()
    scripted_source.failure = OSError("offline")
    assert sales.bind_with_status().status is BindingStatus.CACHED
    support = support_binder.bind_with_status()
    assert support.status is BindingStatus.EMPTY
    assert support.direction.constitution == "support"


def test_given_an_older_reply_when_the_cell_holds_newer_direction_then_the_binding_is_cached(
    scripted_source,
):
    scripted_source.set("sales", 5, "New")
    binder = DirectionBinder(scripted_source, "sales")
    first = binder.bind_with_status()
    scripted_source.set("sales", 4, "Old")
    retained = binder.bind_with_status()
    assert retained.direction is first.direction
    assert retained.status is BindingStatus.CACHED
    assert first.status is BindingStatus.PULLED


def test_given_uncached_sales_when_bind_is_called_then_it_returns_direction_after_one_pull(
    scripted_source,
):
    scripted_source.set("sales", 2, "Sales")
    direction = DirectionBinder(scripted_source, "sales").bind()
    assert isinstance(direction, Direction)
    assert direction.version == 2
    assert scripted_source.calls == [(0, "sales")]


@pytest.mark.parametrize("context", list(DetailLevel))
def test_given_two_binders_when_only_one_has_cached_direction_then_failed_pulls_use_own_state(
    scripted_source, context
):
    first = DirectionBinder(scripted_source, context=context)
    second = DirectionBinder(scripted_source, context=context)
    scripted_source.set("default", 2, "M2")
    original = first.bind()
    scripted_source.failure = OSError("offline")

    populated = first.bind_with_status()
    empty = second.bind_with_status()

    assert populated.status is BindingStatus.CACHED
    assert populated.direction is original
    assert empty.status is BindingStatus.EMPTY
    assert empty.direction == Direction.empty("default", context)
    assert empty.recording is None


def test_given_compact_and_full_binders_when_pulls_fail_then_each_retains_its_requested_context(
    scripted_source,
):
    compact = DirectionBinder(scripted_source, context=DetailLevel.COMPACT)
    full = DirectionBinder(scripted_source, context=DetailLevel.FULL)
    scripted_source.set("default", 2, "M2")
    compact_direction = compact.bind()
    full_direction = full.bind()
    scripted_source.failure = OSError("offline")

    assert compact.bind() is compact_direction
    assert full.bind() is full_direction
    assert compact_direction.context is DetailLevel.COMPACT
    assert full_direction.context is DetailLevel.FULL


@pytest.mark.parametrize("status", list(RecordingStatus))
def test_given_server_receipt_when_bind_with_status_runs_then_recording_is_separate_from_direction(
    scripted_source, status
):
    scripted_source.set("sales", 3, "Sales")
    receipt = RecordingReceipt(status, "record-1" if status is RecordingStatus.RECORDED else None)
    source = SimpleNamespace(
        changes_since=lambda *args: DirectionResponse(scripted_source.replies["sales"], receipt)
    )

    binding = DirectionBinder(source, "sales").bind_with_status()

    assert binding.recording is receipt
    assert binding.status is BindingStatus.PULLED
    assert "recording" not in binding.direction.to_dict()
    assert "record-1" not in binding.direction.render()


@pytest.mark.parametrize("version", [3, 4], ids=["same-version", "newer-version"])
@pytest.mark.parametrize(
    "recording",
    [
        None,
        RecordingReceipt("recorded", "record-2"),
        RecordingReceipt("disabled"),
        RecordingReceipt("failed"),
    ],
    ids=["no-receipt", "recorded", "disabled", "failed"],
)
def test_given_later_response_when_bind_with_status_runs_then_cached_receipt_is_replaced(
    scripted_source,
    version,
    recording,
):
    scripted_source.set("sales", 3, "Sales")
    original_receipt = RecordingReceipt("recorded", "record-1")
    original_response = DirectionResponse(scripted_source.replies["sales"], original_receipt)
    scripted_source.set("sales", version, "Latest sales")
    latest_response = DirectionResponse(scripted_source.replies["sales"], recording)
    responses = iter([original_response, latest_response])

    def changes_since(*args):
        if scripted_source.failure:
            raise scripted_source.failure
        return next(responses)

    binder = DirectionBinder(SimpleNamespace(changes_since=changes_since), "sales")

    first = binder.bind_with_status()
    second = binder.bind_with_status()

    assert first.recording is original_receipt
    assert first.direction.version == 3
    assert second.recording is recording
    assert second.direction.version == version
    assert second.status is BindingStatus.PULLED

    scripted_source.failure = OSError("offline")
    fallback = binder.bind_with_status()
    assert fallback.recording is recording
    assert fallback.direction is second.direction
    assert fallback.status is BindingStatus.CACHED


@pytest.mark.parametrize(
    "recording",
    [
        None,
        RecordingReceipt("recorded", "origin"),
        RecordingReceipt("disabled"),
        RecordingReceipt("failed"),
    ],
)
def test_given_two_binders_when_pulls_fail_then_each_returns_its_own_direction_and_receipt(
    scripted_source, recording
):
    scripted_source.set("sales", 3, "Sales")
    replies = iter(
        [
            DirectionResponse(scripted_source.replies["sales"], recording),
            DirectionResponse(
                scripted_source.replies["sales"], RecordingReceipt("recorded", "other")
            ),
        ]
    )

    def changes_since(*args):
        if scripted_source.failure:
            raise scripted_source.failure
        return next(replies)

    source = SimpleNamespace(changes_since=changes_since)
    first = DirectionBinder(source, "sales")
    second = DirectionBinder(source, "sales")
    original = first.bind_with_status()
    other = second.bind_with_status()
    scripted_source.failure = OSError("offline")

    first_fallback = first.bind_with_status()
    second_fallback = second.bind_with_status()

    assert first_fallback.direction is original.direction
    assert first_fallback.recording is recording
    assert second_fallback.direction is other.direction
    assert second_fallback.recording is other.recording
    assert first_fallback.status is second_fallback.status is BindingStatus.CACHED


def test_given_empty_cache_when_bind_with_status_cannot_pull_then_recording_is_none(
    scripted_source,
):
    scripted_source.failure = OSError("offline")
    assert DirectionBinder(scripted_source).bind_with_status().recording is None


def test_given_two_binders_when_pulls_overlap_then_each_caches_its_own_direction_and_receipt(
    scripted_source,
):
    scripted_source.set("sales", 4, "First consumer")
    first_response = DirectionResponse(
        scripted_source.replies["sales"], RecordingReceipt("recorded", "first")
    )
    scripted_source.set("sales", 5, "Second consumer")
    second_response = DirectionResponse(
        scripted_source.replies["sales"], RecordingReceipt("recorded", "second")
    )
    started = Event()
    release = Event()

    def changes_since(*args):
        if scripted_source.failure:
            raise scripted_source.failure
        if started.is_set():
            return second_response
        started.set()
        assert release.wait(timeout=10)
        return first_response

    source = SimpleNamespace(changes_since=changes_since)
    first = DirectionBinder(source, "sales")
    second = DirectionBinder(source, "sales")
    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(first.bind_with_status)
        try:
            assert started.wait(timeout=10)
            second_binding = second.bind_with_status()
        finally:
            release.set()
        first_binding = pending.result(timeout=10)

    assert first_binding.direction.version == 4
    assert first_binding.recording is first_response.recording
    assert second_binding.direction.version == 5
    assert second_binding.recording is second_response.recording
    assert first_binding.status is second_binding.status is BindingStatus.PULLED

    scripted_source.failure = OSError("offline")
    first_fallback = first.bind_with_status()
    second_fallback = second.bind_with_status()
    assert first_fallback.direction is first_binding.direction
    assert first_fallback.recording is first_binding.recording
    assert second_fallback.direction is second_binding.direction
    assert second_fallback.recording is second_binding.recording
    assert first_fallback.status is second_fallback.status is BindingStatus.CACHED


@pytest.mark.parametrize(
    "older_version",
    [4, 5],
    ids=["older-version-keeps-cached-receipt", "equal-version-uses-response-receipt"],
)
def test_given_late_reply_when_bind_with_status_runs_then_only_older_versions_keep_cached_receipt(
    scripted_source,
    older_version,
):
    scripted_source.set("sales", older_version, "Old")
    older = DirectionResponse(
        scripted_source.replies["sales"], RecordingReceipt("recorded", "older")
    )
    scripted_source.set("sales", 5, "New")
    newer = DirectionResponse(
        scripted_source.replies["sales"], RecordingReceipt("recorded", "newer")
    )
    started = Event()
    release = Event()

    def delayed_changes(*args):
        if started.is_set():
            return newer
        started.set()
        assert release.wait(timeout=10)
        return older

    binder = DirectionBinder(SimpleNamespace(changes_since=delayed_changes), "sales")
    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(binder.bind_with_status)
        try:
            assert started.wait(timeout=10)
            current = binder.bind_with_status()
        finally:
            release.set()
        retained = pending.result(timeout=10)

    assert current.recording is newer.recording
    if older_version < 5:
        assert retained.recording is newer.recording
        assert retained.direction is current.direction
        assert retained.status is BindingStatus.CACHED
    else:
        assert retained.recording is older.recording
        assert retained.status is BindingStatus.PULLED
