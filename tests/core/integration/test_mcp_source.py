"""MCP direction-source behavior over the in-memory server."""

import pytest

from kyno.delivery import RecordingPolicy
from kyno.delivery_recording import DeliveryRecorder
from kyno.sdk.binder import DirectionBinder
from kyno.sdk.client import DirectionSource, LocalDirectionSource, McpDirectionSource
from kyno.sdk.errors import KynoUnavailableError
from kyno.store.delivery_record import SqlDeliveryRecordStore
from kyno.wire.delivery import RecordingStatus
from kyno.wire.models import DetailLevel


def test_given_recording_enabled_when_sdk_pulls_twice_then_each_receipt_identifies_its_own_record(
    mcp_runner,
):
    runner, control_plane = mcp_runner
    history = SqlDeliveryRecordStore(control_plane._store.engine)
    control_plane.delivery_recorder = DeliveryRecorder(history, RecordingPolicy.ALWAYS)
    control_plane.apply_direction(mission="Help customers.", change_note="Initial direction")
    source = McpDirectionSource(runner)

    first = source.changes_since(0, "default")
    second = source.changes_since(1, "default")

    assert first.recording.status is RecordingStatus.RECORDED
    assert second.recording.status is RecordingStatus.RECORDED
    assert first.recording.record_id != second.recording.record_id
    for response, last_seen_version in [(first, 0), (second, 1)]:
        record = history.get(response.recording.record_id)
        assert record["served_version"] == response.changes.current_version == 1
        assert record["last_seen_version"] == last_seen_version
        assert record["delta"] == list(response.changes.delta)
    assert first.changes.changed is True
    assert second.changes.changed is False


def test_given_recording_fails_when_sdk_pulls_then_current_direction_and_failed_receipt_return(
    mcp_runner, monkeypatch
):
    runner, control_plane = mcp_runner
    history = SqlDeliveryRecordStore(control_plane._store.engine)
    control_plane.delivery_recorder = DeliveryRecorder(history, RecordingPolicy.ALWAYS)
    control_plane.apply_direction(mission="Help customers.", change_note="Initial direction")

    def unavailable_store(*args, **kwargs):
        raise OSError("Recording store unavailable")

    monkeypatch.setattr(history, "append", unavailable_store)

    response = McpDirectionSource(runner).changes_since(0, "default")

    assert response.changes.current_version == 1
    assert response.changes.mission == "Help customers."
    assert response.recording.status is RecordingStatus.FAILED
    assert response.recording.record_id is None
    assert history.list()["items"] == []


def test_given_eu_and_us_when_mcp_changes_since_receives_each_key_then_selected_mission_returns(
    mcp_runner,
):
    runner, control_plane = mcp_runner
    control_plane.apply_direction(mission="EU mission", change_note="init", constitution_key="eu")
    control_plane.apply_direction(mission="US mission", change_note="init", constitution_key="us")
    source = McpDirectionSource(runner)

    eu_changes = source.changes_since(0, "eu").changes
    us_changes = source.changes_since(0, "us").changes

    assert eu_changes.mission == "EU mission"
    assert us_changes.mission == "US mission"


def test_given_a_last_seen_version_when_the_mcp_source_reports_then_the_notes_since_come(
    mcp_runner,
):
    runner, control_plane = mcp_runner
    control_plane.apply_direction(mission="M1", change_note="init")
    control_plane.apply_direction(mission="M2", change_note="pivot")
    source = McpDirectionSource(runner)

    changes = source.changes_since(1, "default").changes

    assert changes.current_version == 2 and changes.changed is True
    assert changes.change_notes == ("pivot",)


def test_given_an_unwritten_name_when_the_mcp_source_reads_then_it_is_version_zero(
    mcp_runner,
):
    runner, _cp = mcp_runner
    assert McpDirectionSource(runner).changes_since(0, "never-written").changes.current_version == 0


def test_given_eu_update_when_mcp_binder_bind_runs_again_then_version_two_replaces_version_one(
    mcp_runner,
):
    runner, control_plane = mcp_runner
    control_plane.apply_direction(
        mission="Initial mission", change_note="init", constitution_key="eu"
    )
    binder = DirectionBinder(McpDirectionSource(runner), "eu")

    first = binder.bind()
    control_plane.apply_direction(
        mission="Updated mission", change_note="pivot", constitution_key="eu"
    )
    second = binder.bind()

    assert first.version == 1
    assert second.version == 2
    assert second.mission == "Updated mission"


def test_given_a_closed_runner_when_pulling_then_unavailable_raises_instead_of_hanging(
    mcp_runner,
):
    runner, _cp = mcp_runner
    runner.close()

    with pytest.raises(KynoUnavailableError):
        McpDirectionSource(runner).changes_since(0, "default")


def test_given_the_mcp_source_when_checking_the_protocol_then_it_satisfies_it(mcp_runner):
    runner, _cp = mcp_runner
    assert isinstance(McpDirectionSource(runner), DirectionSource)


def test_given_eu_principles_update_when_local_and_mcp_changes_since_receive_one_then_changes_match(
    mcp_runner,
):
    runner, control_plane = mcp_runner
    control_plane.apply_direction(mission="M1", change_note="init", constitution_key="eu")
    control_plane.apply_direction(
        principles=("Be honest",), change_note="add", constitution_key="eu"
    )

    over_mcp = McpDirectionSource(runner).changes_since(1, "eu")
    in_process = LocalDirectionSource(control_plane).changes_since(1, "eu")

    assert over_mcp.changes == in_process.changes
    assert over_mcp.recording.status.value == "disabled"
    assert in_process.recording is None


def test_given_kyno_going_away_when_a_crew_is_running_then_the_last_direction_carries_it(
    mcp_runner,
    caplog,
):
    runner, control_plane = mcp_runner
    control_plane.apply_direction(mission="M1", change_note="init")
    binder = DirectionBinder(McpDirectionSource(runner))
    binder.bind()

    runner.close()
    direction = binder.bind()

    assert direction.version == 1 and direction.mission == "M1"
    assert "pull_failed_cached" in caplog.text


def test_given_no_message_handler_when_the_session_opens_then_it_is_refused(mcp_runner):
    """The handler is handed to the session once, at open time."""
    runner, _cp = mcp_runner
    with pytest.raises(RuntimeError):
        runner.set_message_handler(lambda message: None)


def test_given_a_closed_runner_when_closing_again_then_it_is_harmless(mcp_runner):
    runner, _cp = mcp_runner
    runner.close()
    runner.close()


def test_given_a_full_binding_when_pulling_then_the_declaration_and_descriptions_come(
    mcp_runner,
):
    runner, control_plane = mcp_runner
    control_plane.apply_direction(
        mission="M1",
        declaration="The long form.",
        principles=({"title": "Be honest", "description": "Say the hard number first."},),
        change_note="init",
    )
    source = McpDirectionSource(runner)

    compact = source.changes_since(0, "default").changes
    full = source.changes_since(0, "default", DetailLevel.FULL).changes

    assert compact.declaration == ""
    assert compact.principles[0].description == ""
    assert full.declaration == "The long form."
    assert full.principles[0].description == "Say the hard number first."
