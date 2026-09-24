"""Whitespace around a key does not create a second directional identity."""

from unittest.mock import Mock

import yaml

from kyno.authoring import read_constitution_file, render_constitution_yaml
from kyno.sdk.binder import DirectionBinder
from kyno.sdk.cell import Direction
from kyno.service import ControlPlane
from kyno.store.delivery_record import SqlDeliveryRecordStore


def test_given_existing_key_when_apply_direction_uses_padded_key_then_same_history_gets_version_two(
    memory_store,
):
    plane = ControlPlane(memory_store)
    plane.apply_direction(mission="First", change_note="init", constitution="support")
    result = plane.apply_direction(
        mission="Second", change_note="update", constitution=" \tsupport\n", expected_version=1
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
