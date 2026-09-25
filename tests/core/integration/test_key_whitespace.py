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
def test_given_empty_store_when_applying_padded_key_then_only_trimmed_identity_is_persisted(
    memory_store, key
):
    result = ControlPlane(memory_store).apply_direction(
        mission="Help", change_note="init", constitution_key=key, expected_version=0
    )

    constitutions = memory_store.metadata.tables["kyno_constitutions"]
    versions = memory_store.metadata.tables["kyno_constitution_versions"]
    with memory_store.engine.connect() as connection:
        assert connection.execute(
            select(constitutions.c.name, constitutions.c.current_version)
        ).all() == [("support", 1)]
        assert connection.execute(
            select(constitutions.c.name, versions.c.version).join(versions)
        ).all() == [("support", 1)]
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
def test_given_empty_store_when_applying_invalid_padded_key_then_no_identity_or_version_is_written(
    memory_store, key
):
    with pytest.raises(ValueError, match="constitution key"):
        ControlPlane(memory_store).apply_direction(
            mission="Help", change_note="init", constitution_key=key
        )

    with memory_store.engine.connect() as connection:
        for name in ("kyno_constitutions", "kyno_constitution_versions"):
            assert connection.execute(select(memory_store.metadata.tables[name])).all() == []


def test_given_key_at_write_limit_when_applying_with_padding_then_only_key_counts_toward_limit(
    memory_store,
):
    key = "a" * 200
    ControlPlane(memory_store).apply_direction(
        mission="Help", change_note="init", constitution_key=f" \t{key}\n"
    )

    table = memory_store.metadata.tables["kyno_constitutions"]
    with memory_store.engine.connect() as connection:
        assert connection.scalars(select(table.c.name)).all() == [key]


def test_given_existing_version_when_padded_apply_expects_empty_then_no_second_identity_is_created(
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
        assert connection.execute(select(constitutions.c.name)).all() == [("support",)]
        assert connection.execute(select(versions.c.version, versions.c.mission)).all() == [
            (1, "First")
        ]


def test_given_served_version_when_recording_padded_key_then_trimmed_key_links_to_that_constitution(
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
        assert connection.execute(
            select(
                records.c.record_id,
                records.c.requested_constitution,
                constitutions.c.name,
                records.c.served_version,
            ).join(constitutions)
        ).all() == [(identifier, "support", "support", 1)]


def test_given_existing_key_when_apply_direction_uses_padded_key_then_same_history_gets_version_two(
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


def test_given_padded_key_when_creating_binder_and_empty_direction_then_both_store_trimmed_key():
    assert DirectionBinder(Mock(), " support ").constitution == "support"
    assert Direction.empty(" support ").constitution == "support"


def test_given_padded_yaml_key_when_reading_and_rendering_authoring_then_output_uses_trimmed_key(
    tmp_path,
    memory_store,
):
    path = tmp_path / "direction.yaml"
    path.write_text('constitution: " support "\nmission: Help\n')
    assert read_constitution_file(str(path)).constitution == "support"
    rendered = render_constitution_yaml(ControlPlane(memory_store).current(), " support ")
    assert yaml.safe_load(rendered)["constitution"] == "support"


def test_given_two_keys_when_delivery_list_uses_padded_filter_then_only_matching_records_return(
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
    records = history.list(constitution=" support ")["items"]
    assert len(records) == 1
    assert records[0]["record_id"] == identifiers[" support "]
    table = memory_store.metadata.tables["kyno_delivery_records"]
    with memory_store.engine.connect() as connection:
        assert connection.scalars(
            select(table.c.requested_constitution).order_by(table.c.sequence)
        ).all() == ["support", "sales"]
