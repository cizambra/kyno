"""Local SDK source behavior against a real control plane."""

import pytest

from kyno.sdk.client import DirectionSource, LocalDirectionSource


def test_given_two_keys_when_local_changes_since_receives_each_key_then_selected_mission_returns(
    control_plane,
):
    control_plane.apply_direction(mission="EU mission", change_note="init", constitution_key="eu")
    control_plane.apply_direction(mission="US mission", change_note="init", constitution_key="us")
    source = LocalDirectionSource(control_plane)

    eu_changes = source.changes_since(0, "eu").changes
    us_changes = source.changes_since(0, "us").changes

    assert eu_changes.mission == "EU mission"
    assert us_changes.mission == "US mission"


def test_given_unwritten_key_when_local_changes_since_runs_then_version_is_zero(control_plane):
    response = LocalDirectionSource(control_plane).changes_since(0, "never-written")
    assert response.recording is None
    changes = response.changes
    assert changes.current_version == 0 and changes.changed is False


def test_given_local_source_when_isinstance_checks_direction_source_then_it_returns_true(
    control_plane,
):
    assert isinstance(LocalDirectionSource(control_plane), DirectionSource)


def test_given_future_last_seen_version_when_local_changes_since_runs_then_unknown_version_raises(
    control_plane,
):
    from kyno.errors import UnknownVersionError

    control_plane.apply_direction(mission="M", change_note="init")
    with pytest.raises(UnknownVersionError):
        LocalDirectionSource(control_plane).changes_since(
            last_seen_version=99, constitution_key="default"
        )


def test_given_other_key_updated_when_local_changes_since_reads_selected_key_then_it_is_unchanged(
    control_plane,
):
    control_plane.apply_direction(mission="EU v1", change_note="init", constitution_key="eu")
    control_plane.apply_direction(mission="US v1", change_note="init", constitution_key="us")
    source = LocalDirectionSource(control_plane)

    control_plane.apply_direction(mission="EU v2", change_note="pivot", constitution_key="eu")

    after_eu = source.changes_since(1, "eu").changes
    after_us = source.changes_since(1, "us").changes
    assert after_eu.changed is True
    assert after_eu.mission == "EU v2"
    assert after_us.changed is False
    assert after_us.mission == "US v1"


def test_given_updates_when_local_changes_since_runs_then_notes_after_last_seen_version_return(
    control_plane,
):
    control_plane.apply_direction(mission="M", change_note="init")
    control_plane.apply_direction(principles=("P",), change_note="add P")
    control_plane.apply_direction(mission="M2", change_note="repoint")

    changes = LocalDirectionSource(control_plane).changes_since(1, "default").changes
    assert changes.current_version == 3
    assert changes.change_notes == ("add P", "repoint")
    assert changes.changed_mission is True and changes.changed_principles is True
