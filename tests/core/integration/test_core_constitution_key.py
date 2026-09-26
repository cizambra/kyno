"""Embedded control-plane operations select constitution keys independently."""

import pytest

from kyno.errors import UnknownVersionError
from kyno.service import ControlPlane


def test_given_two_histories_when_export_versions_selects_key_and_range_then_only_matches_return(
    memory_store,
):
    plane = ControlPlane(memory_store)
    plane.apply_direction(constitution_key="default", mission="Default first", change_note="init")
    plane.apply_direction(
        constitution_key="default", mission="Default second", change_note="update"
    )
    plane.apply_direction(constitution_key="eu-west", mission="EU first", change_note="init")
    plane.apply_direction(constitution_key="eu-west", mission="EU second", change_note="update")
    plane.apply_direction(constitution_key="eu-west", mission="EU third", change_note="update")

    exported_versions = plane.export_versions(
        constitution_key="eu-west", from_version=2, to_version=2
    )

    assert len(exported_versions) == 1
    exported_version = exported_versions[0]
    assert exported_version["version"] == 2
    assert exported_version["mission"] == "EU second"


def test_given_named_head_when_preview_edit_and_head_and_delta_use_same_mission_then_delta_is_empty(
    memory_store,
):
    plane = ControlPlane(memory_store)
    plane.apply_direction(mission="Default mission", change_note="init")
    plane.apply_direction(mission="EU first", change_note="init", constitution_key="eu-west")
    plane.apply_direction(mission="EU second", change_note="update", constitution_key="eu-west")

    preview = plane.preview_edit(mission="EU second", constitution_key=" eu-west ")
    head, delta = plane.head_and_delta(mission="EU second", constitution_key=" eu-west ")

    assert preview == ()
    assert head.version == 2
    assert head.mission == "EU second"
    assert delta == ()
    assert plane.current().mission == "Default mission"
    assert plane.current("eu-west").version == 2


def test_given_private_keys_when_publish_receives_named_key_then_default_remains_private(
    memory_store,
):
    plane = ControlPlane(memory_store)
    plane.apply_direction(mission="Default mission", change_note="init")
    plane.apply_direction(mission="EU first", change_note="init", constitution_key="eu-west")
    plane.apply_direction(mission="EU second", change_note="update", constitution_key="eu-west")

    publication = plane.publish(constitution_key=" eu-west ", with_history=True)

    assert publication.published is True
    assert plane.publication(constitution_key="eu-west").published is True
    public = plane.public_constitution(constitution_key="eu-west")
    assert public.name == "eu-west"
    assert public.mission == "EU second"
    assert public.history is not None
    assert not plane.publication().published
    assert plane.public_constitution() is None


def test_given_public_keys_when_unpublish_receives_named_key_then_default_stays_public(
    memory_store,
):
    plane = ControlPlane(memory_store)
    plane.apply_direction(mission="Default mission", change_note="init")
    plane.apply_direction(mission="EU mission", change_note="init", constitution_key="eu-west")
    plane.publish()
    plane.publish(constitution_key="eu-west")

    publication = plane.unpublish(constitution_key=" eu-west ")

    assert publication.published is False
    assert not plane.publication(constitution_key="eu-west").published
    assert plane.public_constitution(constitution_key="eu-west") is None
    assert plane.publication().published
    assert plane.public_constitution().mission == "Default mission"


def test_given_empty_store_when_apply_direction_receives_named_key_then_only_named_history_starts(
    memory_store,
):
    plane = ControlPlane(memory_store)

    plane.apply_direction(mission="EU mission", change_note="init", constitution_key=" eu-west ")

    assert plane.current(constitution_key="eu-west").mission == "EU mission"
    assert plane.get_constitution(constitution_key="eu-west", version=1).mission == "EU mission"
    assert plane.changes_since(0, constitution_key="eu-west").current_version == 1
    exported_versions = plane.export_versions(constitution_key="eu-west")
    assert len(exported_versions) == 1
    assert exported_versions[0]["version"] == 1
    assert exported_versions[0]["mission"] == "EU mission"
    assert plane.current().version == 0


def test_given_head_when_preview_edit_and_head_and_delta_use_new_mission_then_mission_delta_returns(
    memory_store,
):
    plane = ControlPlane(memory_store)
    plane.apply_direction(mission="EU mission", change_note="init", constitution_key="eu-west")

    preview = plane.preview_edit(mission="Next mission", constitution_key="eu-west")
    head, delta = plane.head_and_delta(mission="Next mission", constitution_key="eu-west")

    assert preview == ('The mission was "EU mission" and is now "Next mission".',)
    assert head.version == 1
    assert head.mission == "EU mission"
    assert delta == ('The mission was "EU mission" and is now "Next mission".',)


@pytest.mark.parametrize(
    "key, expected_mission", [(None, "Default mission"), ("eu-west", "EU mission")]
)
@pytest.mark.parametrize(
    "operation, arguments",
    [
        ("current", {}),
        ("get_constitution", {"version": 1}),
        ("changes_since", {"last_seen_version": 0}),
    ],
)
def test_given_keys_when_current_get_constitution_or_changes_since_runs_then_key_selects_mission(
    memory_store, key, expected_mission, operation, arguments
):
    plane = ControlPlane(memory_store)
    plane.apply_direction(mission="Default mission", change_note="init")
    plane.apply_direction(mission="EU mission", change_note="init", constitution_key="eu-west")

    selected = getattr(plane, operation)(constitution_key=key, **arguments)

    assert selected.mission == expected_mission


def test_given_unknown_key_when_get_constitution_requests_version_then_unknown_version_raises(
    memory_store,
):
    plane = ControlPlane(memory_store)
    plane.apply_direction(mission="Default mission", change_note="init")
    with pytest.raises(UnknownVersionError, match="missing-key"):
        plane.get_constitution(constitution_key="missing-key", version=1)


@pytest.mark.parametrize("key", ["", " ", "Upper"])
def test_given_invalid_key_when_get_constitution_requests_version_zero_then_key_is_refused(
    memory_store, key
):
    with pytest.raises(ValueError, match="constitution key"):
        ControlPlane(memory_store).get_constitution(constitution_key=key, version=0)
