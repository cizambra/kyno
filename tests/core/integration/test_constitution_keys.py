"""Constitution boundaries share one normalized database identity."""

from unittest.mock import Mock

import pytest

from kyno.authoring import read_constitution_file
from kyno.sdk.binder import DirectionBinder
from kyno.sdk.cell import Direction
from kyno.service import ControlPlane
from kyno.store.delivery_record import SqlDeliveryRecordStore


def test_given_padded_key_when_writing_direction_then_reads_and_history_share_one_identity(
    memory_store,
):
    plane = ControlPlane(memory_store)
    plane.apply_direction(mission="EU mission", change_note="init", constitution=" eu-west ")
    assert plane.current("eu-west").mission == "EU mission"
    assert memory_store.head(" eu-west ").mission == "EU mission"
    assert memory_store.export_versions(" eu-west ")[0]["mission"] == "EU mission"
    assert plane.publish(" eu-west ").published
    assert plane.public_constitution("eu-west").name == "eu-west"


@pytest.mark.parametrize("key", ["", " ", "Upper", "bad/name", "a" * 201])
def test_given_invalid_key_when_reading_or_importing_then_no_identity_is_created(memory_store, key):
    with pytest.raises(ValueError, match="constitution key"):
        ControlPlane(memory_store).current(key)
    with pytest.raises(ValueError, match="constitution key"):
        ControlPlane(memory_store).get_constitution(key, version=0)
    with pytest.raises(ValueError, match="constitution key"):
        memory_store.import_versions(key, [])


def test_given_padded_key_when_constructing_sdk_values_then_identity_is_normalized():
    assert DirectionBinder(Mock(), " eu-west ").constitution == "eu-west"
    assert Direction.empty(" eu-west ").constitution == "eu-west"
    assert DirectionBinder(Mock(), None).constitution == "default"


def test_given_padded_file_key_when_reading_authoring_then_identity_is_normalized(tmp_path):
    path = tmp_path / "constitution.yaml"
    path.write_text('constitution: " eu-west "\nmission: Help\n')
    assert read_constitution_file(str(path)).constitution == "eu-west"


@pytest.mark.parametrize("key", ["", " ", "Acme EU", "a" * 201])
def test_given_invalid_file_key_when_reading_authoring_then_key_is_refused(tmp_path, key):
    path = tmp_path / "constitution.yaml"
    path.write_text(f'constitution: "{key}"\nmission: Help\n')
    with pytest.raises(ValueError, match="constitution key"):
        read_constitution_file(str(path))


def test_given_delivery_filters_when_listing_then_none_means_all_and_padded_key_matches(
    memory_store,
):
    history = SqlDeliveryRecordStore(memory_store.engine)
    for key in (" eu-west ", "default"):
        history.append(
            {"version": 0},
            operation="get_direction",
            constitution=key,
            arguments={},
            context={"correlation_id": None, "metadata": {}},
        )
    assert len(history.list()["items"]) == 2
    assert len(history.list(constitution=" eu-west ")["items"]) == 1
    with pytest.raises(ValueError, match="constitution key"):
        history.list(constitution=" ")


@pytest.mark.parametrize(
    "operation, arguments",
    [
        ("head", {}),
        ("get", {"version": 1}),
        ("versions_after", {"last_seen_version": 0}),
        ("export_versions", {}),
        ("import_versions", {"rows": []}),
        ("publication", {}),
        ("set_publication", {"published_at": None, "history_public": False}),
        (
            "append",
            {
                "version": 1,
                "mission": "Help",
                "principles": (),
                "change_note": "init",
                "changed_mission": True,
                "changed_principles": False,
                "created_by": None,
            },
        ),
    ],
)
@pytest.mark.parametrize("key", [" ", "Upper", "a" * 201])
def test_given_invalid_key_when_using_storage_directly_then_boundary_refuses_it(
    memory_store, operation, arguments, key
):
    with pytest.raises(ValueError, match="constitution key"):
        getattr(memory_store, operation)(key, **arguments)


def test_given_padded_maximum_key_when_using_storage_directly_then_one_identity_is_preserved(
    memory_store,
):
    key = "a" * 200
    padded = f" \n{key}\t "
    stored = memory_store.append(
        padded,
        1,
        mission="Help",
        principles=(),
        change_note="init",
        changed_mission=True,
        changed_principles=False,
        created_by=None,
    )
    assert memory_store.head(key) == stored
    assert memory_store.get(padded, 1) == stored
    assert memory_store.versions_after(padded, 0) == [stored]
    assert memory_store.export_versions(padded)[0]["mission"] == "Help"
    memory_store.import_versions(" copy ", memory_store.export_versions(key))
    assert memory_store.head("copy").mission == "Help"
    assert memory_store.set_publication(padded, published_at=stored.created_at, history_public=True)
    assert memory_store.publication(key).published
    assert memory_store.publication(padded).history_public
