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
    plane.apply_direction(mission="EU mission", change_note="init", constitution_key=" eu-west ")
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
