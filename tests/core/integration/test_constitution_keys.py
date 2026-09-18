"""Constitution boundaries share one normalized database identity."""

from unittest.mock import Mock

import pytest
import yaml

from kyno.authoring import read_constitution_file, render_constitution_yaml
from kyno.sdk.binder import DirectionBinder
from kyno.sdk.cell import Direction
from kyno.service import ControlPlane
from kyno.store.delivery_record import SqlDeliveryRecordStore


def test_given_padded_key_when_apply_direction_runs_then_reads_and_publication_use_trimmed_key(
    memory_store,
):
    plane = ControlPlane(memory_store)
    plane.apply_direction(mission="EU mission", change_note="init", constitution=" eu-west ")
    assert plane.current("eu-west").mission == "EU mission"
    assert memory_store.head(" eu-west ").mission == "EU mission"
    assert memory_store.export_versions(" eu-west ")[0]["mission"] == "EU mission"
    assert plane.publish(" eu-west ").published
    assert plane.public_constitution("eu-west").name == "eu-west"


def test_given_existing_key_when_apply_direction_uses_padded_key_then_same_history_gets_version_two(
    memory_store,
):
    plane = ControlPlane(memory_store)
    plane.apply_direction(mission="First", change_note="init", constitution="support")

    updated = plane.apply_direction(
        mission="Second", change_note="update", constitution=" \tsupport\n", expected_version=1
    )

    assert updated.version == 2
    assert plane.current("support").mission == "Second"
    assert [version.version for version in memory_store.versions_after("support", 0)] == [1, 2]
    assert plane.current().version == 0


@pytest.mark.parametrize("key", [" ", "Upper", "bad/name", "a" * 201])
def test_given_invalid_key_when_delivery_store_append_runs_then_value_error_leaves_history_empty(
    memory_store, key
):
    history = SqlDeliveryRecordStore(memory_store.engine)

    with pytest.raises(ValueError, match="constitution key"):
        history.append(
            {"version": 0},
            operation="get_direction",
            constitution=key,
            arguments={},
            context={"correlation_id": None, "metadata": {}},
        )

    assert history.list()["items"] == []


@pytest.mark.parametrize("key", ["", " ", "Upper", "bad/name", "a" * 201])
def test_given_invalid_key_when_core_reads_or_store_import_runs_then_value_error_is_raised(
    memory_store, key
):
    with pytest.raises(ValueError, match="constitution key"):
        ControlPlane(memory_store).current(key)
    with pytest.raises(ValueError, match="constitution key"):
        ControlPlane(memory_store).get_constitution(key, version=0)
    with pytest.raises(ValueError, match="constitution key"):
        memory_store.import_versions(key, [])


def test_given_padded_key_when_creating_binder_and_empty_direction_then_both_store_trimmed_key():
    assert DirectionBinder(Mock(), " eu-west ").constitution == "eu-west"
    assert Direction.empty(" eu-west ").constitution == "eu-west"
    assert DirectionBinder(Mock(), None).constitution == "default"


def test_given_padded_yaml_key_when_read_constitution_file_runs_then_constitution_is_trimmed(
    tmp_path,
):
    path = tmp_path / "constitution.yaml"
    path.write_text('constitution: " eu-west "\nmission: Help\n')
    assert read_constitution_file(str(path)).constitution == "eu-west"


@pytest.mark.parametrize("key", ["eu-west", "a" * 200])
def test_given_padded_key_when_render_constitution_yaml_runs_then_yaml_contains_trimmed_key(
    memory_store, key
):
    version = ControlPlane(memory_store).current()
    document = yaml.safe_load(render_constitution_yaml(version, f" {key} "))
    assert document["constitution"] == key


@pytest.mark.parametrize("key", [" ", "Upper"])
def test_given_invalid_key_when_render_constitution_yaml_runs_then_value_error_is_raised(
    memory_store, key
):
    with pytest.raises(ValueError, match="constitution key"):
        render_constitution_yaml(ControlPlane(memory_store).current(), key)


@pytest.mark.parametrize("key", ["", " ", "Acme EU", "a" * 201])
def test_given_invalid_yaml_key_when_read_constitution_file_runs_then_value_error_is_raised(
    tmp_path, key
):
    path = tmp_path / "constitution.yaml"
    path.write_text(f'constitution: "{key}"\nmission: Help\n')
    with pytest.raises(ValueError, match="constitution key"):
        read_constitution_file(str(path))


def test_given_two_keys_when_delivery_store_list_filters_by_padded_key_then_only_that_key_returns(
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
def test_given_invalid_key_when_sql_store_operation_runs_then_value_error_is_raised(
    memory_store, operation, arguments, key
):
    with pytest.raises(ValueError, match="constitution key"):
        getattr(memory_store, operation)(key, **arguments)


def test_given_padded_200_character_key_when_sql_store_operations_run_then_trimmed_key_is_used(
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
