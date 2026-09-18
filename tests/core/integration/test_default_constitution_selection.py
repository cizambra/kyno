"""Omitted selections address default without changing another constitution."""

import pytest

from kyno.service import ControlPlane


@pytest.fixture
def plane(memory_store):
    control_plane = ControlPlane(memory_store)
    control_plane.apply_direction(
        mission="Default first", change_note="Initial", constitution="default"
    )
    control_plane.apply_direction(
        mission="Default second", change_note="Updated", constitution="default"
    )
    control_plane.apply_direction(
        mission="Support first", change_note="Initial", constitution="support"
    )
    return control_plane


@pytest.fixture(params=[{}, {"constitution": None}], ids=["omitted", "explicit-none"])
def default_selection(request):
    return request.param


def test_given_a_named_write_when_applying_without_a_selection_then_only_default_advances(
    plane, default_selection
):
    written = plane.apply_direction(
        mission="Default third", change_note="Updated again", **default_selection
    )

    assert written.version == 3
    assert plane.current("default").mission == "Default third"
    assert plane.current("support").version == 1
    assert plane.current("support").mission == "Support first"


def test_given_no_constitution_when_get_constitution_requests_v1_then_default_v1_is_returned(
    plane, default_selection
):
    direction = plane.get_constitution(version=1, **default_selection)

    assert direction.version == 1
    assert direction.mission == "Default first"


def test_given_no_constitution_when_changes_since_reads_after_v1_then_default_v2_changes_return(
    plane, default_selection
):
    changes = plane.changes_since(1, **default_selection)

    assert changes.current_version == 2
    assert changes.mission == "Default second"
    assert changes.change_notes == ("Updated",)


def test_given_two_histories_when_export_versions_has_no_selection_then_only_default_is_exported(
    plane, default_selection
):
    versions = plane.export_versions(**default_selection)

    assert [version["mission"] for version in versions] == ["Default first", "Default second"]


def test_given_current_default_content_when_preview_edit_has_no_selection_then_it_reports_no_change(
    plane, default_selection
):
    assert plane.preview_edit(mission="Default second", **default_selection) == ()


def test_given_default_content_when_head_and_delta_has_no_selection_then_default_head_returns(
    plane, default_selection
):
    head, delta = plane.head_and_delta(mission="Default second", **default_selection)

    assert head.version == 2
    assert head.mission == "Default second"
    assert delta == ()


def test_given_two_private_constitutions_when_publish_has_no_selection_then_only_default_is_public(
    plane, default_selection
):
    plane.publish(**default_selection)

    assert plane.publication(**default_selection).published
    assert plane.public_constitution(**default_selection).mission == "Default second"
    assert not plane.publication("support").published


def test_given_two_public_constitutions_when_unpublish_has_no_selection_then_support_stays_public(
    plane, default_selection
):
    plane.publish("default")
    plane.publish("support")

    plane.unpublish(**default_selection)

    assert not plane.publication(**default_selection).published
    assert plane.public_constitution(**default_selection) is None
    assert plane.publication("support").published
