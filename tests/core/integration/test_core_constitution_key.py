"""Embedded control-plane operations select constitution keys independently."""

import pytest

from kyno.errors import UnknownVersionError
from kyno.service import ControlPlane


@pytest.fixture
def two_directions(memory_store):
    plane = ControlPlane(memory_store)
    plane.apply_direction(mission="Default mission", change_note="init")
    plane.apply_direction(mission="EU first", change_note="init", constitution_key="eu-west")
    plane.apply_direction(mission="EU second", change_note="update", constitution_key="eu-west")
    return plane


def test_given_two_histories_when_exporting_named_key_then_only_selected_version_range_returns(
    two_directions,
):
    rows = two_directions.export_versions(
        constitution_key=" eu-west ", from_version=2, to_version=2
    )
    assert [(row["version"], row["mission"]) for row in rows] == [(2, "EU second")]


def test_given_two_directions_when_previewing_selected_mission_then_selected_head_has_no_delta(
    two_directions,
):
    assert two_directions.preview_edit(mission="EU second", constitution_key=" eu-west ") == ()
    head, delta = two_directions.head_and_delta(mission="EU second", constitution_key=" eu-west ")
    assert (head.version, head.mission, delta) == (2, "EU second", ())
    assert two_directions.current().mission == "Default mission"
    assert two_directions.current("eu-west").version == 2


def test_given_two_directions_when_publishing_named_key_then_default_remains_private(
    two_directions,
):
    plane = two_directions
    plane.publish(constitution_key=" eu-west ", with_history=True)

    assert plane.publication(constitution_key="eu-west").published
    public = plane.public_constitution(constitution_key="eu-west")
    assert (public.name, public.mission) == ("eu-west", "EU second")
    assert public.history is not None
    assert not plane.publication().published
    assert plane.public_constitution() is None


def test_given_two_public_directions_when_unpublishing_named_key_then_default_stays_public(
    two_directions,
):
    plane = two_directions
    plane.publish()
    plane.publish(constitution_key="eu-west")

    plane.unpublish(constitution_key=" eu-west ")

    assert not plane.publication(constitution_key="eu-west").published
    assert plane.public_constitution(constitution_key="eu-west") is None
    assert plane.publication().published
    assert plane.public_constitution().mission == "Default mission"


def test_given_named_direction_when_selecting_key_then_embedded_operations_share_it(memory_store):
    plane = ControlPlane(memory_store)
    plane.apply_direction(mission="EU mission", change_note="init", constitution_key=" eu-west ")
    assert plane.current(constitution_key="eu-west").mission == "EU mission"
    assert plane.get_constitution(constitution_key="eu-west", version=1).mission == "EU mission"
    assert plane.changes_since(0, constitution_key="eu-west").current_version == 1
    assert plane.export_versions(constitution_key="eu-west")[0]["version"] == 1
    assert plane.preview_edit(mission="Next mission", constitution_key="eu-west")
    assert plane.head_and_delta(mission="Next mission", constitution_key="eu-west")[0].version == 1
    assert plane.publish(constitution_key="eu-west").published
    assert plane.publication(constitution_key="eu-west").published
    assert plane.public_constitution(constitution_key="eu-west").name == "eu-west"
    assert not plane.unpublish(constitution_key="eu-west").published
    assert plane.current().version == 0


@pytest.mark.parametrize("key, expected", [(None, "Default mission"), ("eu-west", "EU mission")])
@pytest.mark.parametrize(
    "operation, arguments",
    [
        ("current", {}),
        ("get_constitution", {"version": 1}),
        ("changes_since", {"last_seen_version": 0}),
    ],
)
def test_given_two_directions_when_selecting_key_keyword_then_read_uses_that_selection(
    memory_store, key, expected, operation, arguments
):
    plane = ControlPlane(memory_store)
    plane.apply_direction(mission="Default mission", change_note="init")
    plane.apply_direction(mission="EU mission", change_note="init", constitution_key="eu-west")
    selected = getattr(plane, operation)(constitution_key=key, **arguments)
    assert selected.mission == expected


def test_given_unknown_key_when_requesting_exact_version_by_keyword_then_version_is_not_found(
    memory_store,
):
    plane = ControlPlane(memory_store)
    plane.apply_direction(mission="Default mission", change_note="init")
    with pytest.raises(UnknownVersionError, match="missing-key"):
        plane.get_constitution(constitution_key="missing-key", version=1)


@pytest.mark.parametrize("key", ["", " ", "Upper"])
def test_given_invalid_key_when_requesting_version_zero_by_keyword_then_key_is_refused(
    memory_store, key
):
    with pytest.raises(ValueError, match="constitution key"):
        ControlPlane(memory_store).get_constitution(constitution_key=key, version=0)
