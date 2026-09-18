"""Local SDK source behavior against a real control plane."""

import pytest

from kyno.sdk.client import DirectionSource, LocalDirectionSource


def test_given_a_local_source_when_pulling_a_name_then_that_constitution_serves(control_plane):
    control_plane.apply_direction(mission="EU mission", change_note="init", constitution_key="eu")
    control_plane.apply_direction(mission="US mission", change_note="init", constitution_key="us")
    source = LocalDirectionSource(control_plane)

    assert source.changes_since(0, "eu").changes.mission == "EU mission"
    assert source.changes_since(0, "us").changes.mission == "US mission"


def test_given_an_unwritten_name_when_a_local_source_reads_then_it_is_version_zero(control_plane):
    response = LocalDirectionSource(control_plane).changes_since(0, "never-written")
    assert response.recording is None
    changes = response.changes
    assert changes.current_version == 0 and changes.changed is False


def test_given_the_local_source_when_checking_the_protocol_then_it_satisfies_it(control_plane):
    assert isinstance(LocalDirectionSource(control_plane), DirectionSource)


def test_given_a_future_last_seen_version_when_a_local_source_pulls_then_the_error_propagates(
    control_plane,
):
    from kyno.errors import UnknownVersionError

    control_plane.apply_direction(mission="M", change_note="init")
    with pytest.raises(UnknownVersionError):
        LocalDirectionSource(control_plane).changes_since(
            last_seen_version=99, constitution="default"
        )


def test_given_one_source_when_serving_two_bindings_then_there_is_no_crosstalk(control_plane):
    """The use case: one process runs an EU crew and a US crew off one plane."""
    control_plane.apply_direction(mission="EU v1", change_note="init", constitution_key="eu")
    control_plane.apply_direction(mission="US v1", change_note="init", constitution_key="us")
    source = LocalDirectionSource(control_plane)
    eu, us = "eu", "us"

    control_plane.apply_direction(mission="EU v2", change_note="pivot", constitution_key="eu")

    after_eu = source.changes_since(1, eu).changes
    after_us = source.changes_since(1, us).changes
    assert after_eu.changed is True and after_eu.mission == "EU v2"
    assert after_us.changed is False and after_us.mission == "US v1"


def test_given_a_last_seen_version_when_a_local_source_reports_then_every_note_since_comes(
    control_plane,
):
    control_plane.apply_direction(mission="M", change_note="init")
    control_plane.apply_direction(principles=("P",), change_note="add P")
    control_plane.apply_direction(mission="M2", change_note="repoint")

    changes = LocalDirectionSource(control_plane).changes_since(1, "default").changes
    assert changes.current_version == 3
    assert changes.change_notes == ("add P", "repoint")
    assert changes.changed_mission is True and changes.changed_principles is True
