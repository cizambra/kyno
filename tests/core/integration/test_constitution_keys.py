"""Constitution boundaries share one normalized database identity."""

import pytest

from kyno.authoring import read_constitution_file, render_constitution_yaml
from kyno.service import ControlPlane
from kyno.store.delivery_record import SqlDeliveryRecordStore


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


@pytest.mark.parametrize("key", [" ", "Upper", "a" * 201])
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
    path.write_text(f'constitution_key: "{key}"\nmission: Help\n')
    with pytest.raises(ValueError, match="constitution key"):
        read_constitution_file(str(path))


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
