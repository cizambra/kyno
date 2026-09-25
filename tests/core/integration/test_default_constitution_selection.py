"""Omitted selections address default without changing another constitution."""

import pytest

from kyno.service import ControlPlane


@pytest.fixture(params=[{}, {"constitution_key": None}], ids=["omitted", "explicit-none"])
def default_selection(request):
    return request.param


def test_given_omitted_or_none_key_when_apply_direction_runs_then_only_default_gets_a_new_version(
    memory_store, default_selection
):
    plane = ControlPlane(memory_store)
    plane.apply_direction(
        mission="Default first", change_note="Initial", constitution_key="default"
    )
    plane.apply_direction(
        mission="Default second", change_note="Updated", constitution_key="default"
    )
    plane.apply_direction(
        mission="Support first", change_note="Initial", constitution_key="support"
    )

    written = plane.apply_direction(
        mission="Default third", change_note="Updated again", **default_selection
    )

    assert written.version == 3
    assert plane.current("default").mission == "Default third"
    assert plane.current("support").version == 1
    assert plane.current("support").mission == "Support first"


def test_given_omitted_or_none_key_when_get_constitution_requests_v1_then_default_v1_is_returned(
    memory_store, default_selection
):
    plane = ControlPlane(memory_store)
    plane.apply_direction(
        mission="Default first", change_note="Initial", constitution_key="default"
    )
    plane.apply_direction(
        mission="Default second", change_note="Updated", constitution_key="default"
    )
    plane.apply_direction(
        mission="Support first", change_note="Initial", constitution_key="support"
    )

    direction = plane.get_constitution(version=1, **default_selection)

    assert direction.version == 1
    assert direction.mission == "Default first"


def test_given_omitted_or_none_key_when_changes_since_uses_v1_then_default_v2_changes_return(
    memory_store, default_selection
):
    plane = ControlPlane(memory_store)
    plane.apply_direction(
        mission="Default first", change_note="Initial", constitution_key="default"
    )
    plane.apply_direction(
        mission="Default second", change_note="Updated", constitution_key="default"
    )
    plane.apply_direction(
        mission="Support first", change_note="Initial", constitution_key="support"
    )

    changes = plane.changes_since(1, **default_selection)

    assert changes.current_version == 2
    assert changes.mission == "Default second"
    assert changes.change_notes == ("Updated",)


def test_given_omitted_or_none_key_when_export_versions_runs_then_only_default_history_is_returned(
    memory_store, default_selection
):
    plane = ControlPlane(memory_store)
    plane.apply_direction(
        mission="Default first", change_note="Initial", constitution_key="default"
    )
    plane.apply_direction(
        mission="Default second", change_note="Updated", constitution_key="default"
    )
    plane.apply_direction(
        mission="Support first", change_note="Initial", constitution_key="support"
    )

    versions = plane.export_versions(**default_selection)

    assert [version["mission"] for version in versions] == ["Default first", "Default second"]


def test_given_default_mission_when_preview_omits_or_passes_none_key_then_no_change_is_reported(
    memory_store, default_selection
):
    plane = ControlPlane(memory_store)
    plane.apply_direction(
        mission="Default first", change_note="Initial", constitution_key="default"
    )
    plane.apply_direction(
        mission="Default second", change_note="Updated", constitution_key="default"
    )
    plane.apply_direction(
        mission="Support first", change_note="Initial", constitution_key="support"
    )

    preview = plane.preview_edit(mission="Default second", **default_selection)

    assert preview == ()


def test_given_omitted_or_none_key_when_head_and_delta_runs_then_default_head_and_no_delta_return(
    memory_store, default_selection
):
    plane = ControlPlane(memory_store)
    plane.apply_direction(
        mission="Default first", change_note="Initial", constitution_key="default"
    )
    plane.apply_direction(
        mission="Default second", change_note="Updated", constitution_key="default"
    )
    plane.apply_direction(
        mission="Support first", change_note="Initial", constitution_key="support"
    )

    head, delta = plane.head_and_delta(mission="Default second", **default_selection)

    assert head.version == 2
    assert head.mission == "Default second"
    assert delta == ()


def test_given_omitted_or_none_key_when_publish_runs_then_only_default_becomes_public(
    memory_store, default_selection
):
    plane = ControlPlane(memory_store)
    plane.apply_direction(
        mission="Default first", change_note="Initial", constitution_key="default"
    )
    plane.apply_direction(
        mission="Default second", change_note="Updated", constitution_key="default"
    )
    plane.apply_direction(
        mission="Support first", change_note="Initial", constitution_key="support"
    )

    plane.publish(**default_selection)

    assert plane.publication(**default_selection).published
    assert plane.public_constitution(**default_selection).mission == "Default second"
    assert not plane.publication("support").published


def test_given_omitted_or_none_key_when_unpublish_runs_then_only_default_becomes_private(
    memory_store, default_selection
):
    plane = ControlPlane(memory_store)
    plane.apply_direction(
        mission="Default first", change_note="Initial", constitution_key="default"
    )
    plane.apply_direction(
        mission="Default second", change_note="Updated", constitution_key="default"
    )
    plane.apply_direction(
        mission="Support first", change_note="Initial", constitution_key="support"
    )

    plane.publish("default")
    plane.publish("support")

    plane.unpublish(**default_selection)

    assert not plane.publication(**default_selection).published
    assert plane.public_constitution(**default_selection) is None
    assert plane.publication("support").published
