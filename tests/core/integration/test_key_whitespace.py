"""Whitespace around a key does not create a second directional identity."""

from unittest.mock import Mock

import pytest
import yaml
from sqlalchemy import select

from kyno.authoring import read_constitution_file, render_constitution_yaml
from kyno.errors import VersionConflictError
from kyno.sdk.binder import DirectionBinder
from kyno.sdk.cell import Direction
from kyno.service import ControlPlane
from kyno.store.delivery_record import SqlDeliveryRecordStore
from tests.stores import create_memory_store


@pytest.mark.parametrize("key", [" support ", " \tsupport\n", "\u2003support\u2003"])
def test_given_empty_store_when_apply_direction_receives_padded_key_then_trimmed_identity_persists(
    memory_store, key
):
    result = ControlPlane(memory_store).apply_direction(
        mission="Help", change_note="init", constitution_key=key, expected_version=0
    )

    constitutions = memory_store.metadata.tables["kyno_constitutions"]
    versions = memory_store.metadata.tables["kyno_constitution_versions"]
    with memory_store.engine.connect() as connection:
        stored_constitution = (
            connection.execute(select(constitutions.c.name, constitutions.c.current_version))
            .mappings()
            .one()
        )
        stored_version = (
            connection.execute(select(constitutions.c.name, versions.c.version).join(versions))
            .mappings()
            .one()
        )

    assert stored_constitution["name"] == "support"
    assert stored_constitution["current_version"] == 1
    assert stored_version["name"] == "support"
    assert stored_version["version"] == 1
    assert result.version == 1


@pytest.mark.parametrize("operation", ["append", "import"])
def test_given_empty_store_when_writing_padded_key_directly_then_trimmed_identity_is_persisted(
    memory_store, operation
):
    if operation == "append":
        memory_store.append(
            " \tsupport\n",
            version=1,
            mission="Help",
            principles=(),
            change_note="init",
            changed_mission=True,
            changed_principles=False,
            created_by=None,
        )
    else:
        source = create_memory_store()
        try:
            ControlPlane(source).apply_direction(mission="Help", change_note="init")
            memory_store.import_versions(" \tsupport\n", source.export_versions("default"))
        finally:
            source.engine.dispose()

    constitutions = memory_store.metadata.tables["kyno_constitutions"]
    with memory_store.engine.connect() as connection:
        assert connection.execute(
            select(constitutions.c.name, constitutions.c.current_version)
        ).all() == [("support", 1)]


@pytest.mark.parametrize("key", [" \t\n\u2003", " sup port "])
def test_given_empty_store_when_apply_direction_receives_invalid_padded_key_then_no_rows_written(
    memory_store, key
):
    with pytest.raises(ValueError, match="constitution key"):
        ControlPlane(memory_store).apply_direction(
            mission="Help", change_note="init", constitution_key=key
        )

    with memory_store.engine.connect() as connection:
        for name in ("kyno_constitutions", "kyno_constitution_versions"):
            assert connection.execute(select(memory_store.metadata.tables[name])).all() == []


def test_given_200_character_key_when_apply_direction_receives_padding_then_padding_does_not_count(
    memory_store,
):
    key = "a" * 200
    ControlPlane(memory_store).apply_direction(
        mission="Help", change_note="init", constitution_key=f" \t{key}\n"
    )

    table = memory_store.metadata.tables["kyno_constitutions"]
    with memory_store.engine.connect() as connection:
        assert connection.scalars(select(table.c.name)).all() == [key]


def test_given_stored_key_when_apply_direction_expects_zero_for_padded_key_then_history_unchanged(
    memory_store,
):
    plane = ControlPlane(memory_store)
    plane.apply_direction(mission="First", change_note="init", constitution_key="support")

    with pytest.raises(VersionConflictError):
        plane.apply_direction(
            mission="Second", change_note="update", constitution_key=" support ", expected_version=0
        )

    constitutions = memory_store.metadata.tables["kyno_constitutions"]
    versions = memory_store.metadata.tables["kyno_constitution_versions"]
    with memory_store.engine.connect() as connection:
        stored_keys = connection.scalars(select(constitutions.c.name)).all()
        stored_version = (
            connection.execute(select(versions.c.version, versions.c.mission)).mappings().one()
        )

    assert stored_keys == ["support"]
    assert stored_version["version"] == 1
    assert stored_version["mission"] == "First"


def test_given_version_when_delivery_store_append_receives_padded_key_then_trimmed_key_links_to_it(
    memory_store,
):
    plane = ControlPlane(memory_store)
    plane.apply_direction(mission="Help", change_note="init", constitution_key="support")
    history = SqlDeliveryRecordStore(memory_store.engine)

    identifier = history.append(
        {"version": 1},
        operation="get_direction",
        constitution=" \tsupport\n",
        arguments={},
        context={"correlation_id": None, "metadata": {}},
    )

    constitutions = memory_store.metadata.tables["kyno_constitutions"]
    records = memory_store.metadata.tables["kyno_delivery_records"]
    with memory_store.engine.connect() as connection:
        stored_record = (
            connection.execute(
                select(
                    records.c.record_id,
                    records.c.requested_constitution,
                    constitutions.c.name,
                    records.c.served_version,
                ).join(constitutions)
            )
            .mappings()
            .one()
        )

    assert stored_record["record_id"] == identifier
    assert stored_record["requested_constitution"] == "support"
    assert stored_record["name"] == "support"
    assert stored_record["served_version"] == 1


def test_given_stored_key_when_apply_direction_uses_padded_key_then_same_history_gets_next_version(
    memory_store,
):
    plane = ControlPlane(memory_store)
    plane.apply_direction(mission="First", change_note="init", constitution_key="support")

    result = plane.apply_direction(
        mission="Second", change_note="update", constitution_key=" \tsupport\n", expected_version=1
    )

    assert result.version == 2
    assert plane.current("support").mission == "Second"
    assert [version.version for version in memory_store.versions_after("support", 0)] == [1, 2]
    assert plane.current().version == 0


def test_given_padded_key_when_binder_init_and_direction_empty_then_trimmed_key_is_stored():
    assert DirectionBinder(Mock(), " support ").constitution_key == "support"
    assert Direction.empty(" support ").constitution_key == "support"


def test_given_padded_yaml_key_when_reading_and_rendering_authoring_then_output_uses_trimmed_key(
    tmp_path,
    memory_store,
):
    path = tmp_path / "direction.yaml"
    path.write_text('constitution: " support "\nmission: Help\n')
    assert read_constitution_file(str(path)).constitution == "support"
    rendered = render_constitution_yaml(ControlPlane(memory_store).current(), " support ")
    assert yaml.safe_load(rendered)["constitution"] == "support"


def test_given_padded_filter_when_delivery_store_list_then_only_matching_records_return(
    memory_store,
):
    history = SqlDeliveryRecordStore(memory_store.engine)
    identifiers = {}
    for key in (" support ", "sales"):
        identifiers[key] = history.append(
            {"version": 0},
            operation="get_direction",
            constitution=key,
            arguments={},
            context={"correlation_id": None, "metadata": {}},
        )
    assert len(history.list()["items"]) == 2
    records = history.list(constitution_key=" support ")["items"]
    assert len(records) == 1
    assert records[0]["record_id"] == identifiers[" support "]
    table = memory_store.metadata.tables["kyno_delivery_records"]
    with memory_store.engine.connect() as connection:
        assert connection.scalars(
            select(table.c.requested_constitution).order_by(table.c.sequence)
        ).all() == ["support", "sales"]
