"""Core resolves omitted selectors consistently across its direction operations."""

import pytest

from kyno.delivery_recording import DeliveryRecorder
from kyno.service import ControlPlane
from kyno.store.delivery_record import SqlDeliveryRecordStore


@pytest.mark.parametrize("selector", [{}, {"constitution_key": None}], ids=["omitted", "null"])
@pytest.mark.parametrize(
    "operation, arguments",
    [
        ("current", {}),
        ("get_constitution", {"version": 0}),
        ("get_constitution", {"version": 1}),
        ("changes_since", {"last_seen_version": 0}),
        ("export_versions", {}),
        ("preview_edit", {"mission": "Next"}),
        ("head_and_delta", {"mission": "Next"}),
        ("publication", {}),
        ("public_constitution", {}),
    ],
)
def test_given_omitted_key_when_core_read_operation_runs_then_result_matches_explicit_default(
    memory_store, selector, operation, arguments
):
    plane = ControlPlane(memory_store)
    plane.apply_direction(mission="Default", change_note="init", constitution_key="default")
    plane.apply_direction(mission="Other", change_note="init", constitution_key="support")
    plane.publish(constitution_key="default")
    expected = getattr(plane, operation)(constitution_key="default", **arguments)

    assert getattr(plane, operation)(**selector, **arguments) == expected


@pytest.mark.parametrize("selector", [{}, {"constitution_key": None}], ids=["omitted", "null"])
@pytest.mark.parametrize("operation", ["publish", "unpublish"])
def test_given_omitted_key_when_publish_or_unpublish_then_only_default_visibility_changes(
    memory_store, selector, operation
):
    plane = ControlPlane(memory_store)
    plane.apply_direction(mission="Default mission", change_note="Initial")
    plane.apply_direction(
        constitution_key="support", mission="Support mission", change_note="Initial"
    )
    if operation == "unpublish":
        plane.publish("default")
        plane.publish("support")
    original_support = plane.publication("support")
    assert plane.publication("default").published is (operation == "unpublish")

    result = getattr(plane, operation)(**selector)

    assert result.constitution_key == "default"
    assert result.published is (operation == "publish")
    assert plane.publication("default") == result
    assert plane.publication("support") == original_support


@pytest.mark.parametrize("arguments", [{}, {"constitution_key": None}], ids=["omitted", "null"])
def test_given_omitted_key_when_record_delivery_then_stored_record_identifies_default(
    memory_store, arguments
):
    history = SqlDeliveryRecordStore(memory_store.engine)
    plane = ControlPlane(memory_store, delivery_recorder=DeliveryRecorder(history, "always"))
    current = plane.apply_direction(mission="Default mission", change_note="Initial")

    receipt = plane.record_delivery(
        current.to_dict(), operation="get_constitution", arguments=arguments
    )

    record = history.get(receipt["record_id"])
    assert record["constitution_key"] == "default"
    assert record["served_version"] == current.version


def test_given_omitted_key_when_sql_store_export_versions_then_required_argument_error_is_raised(
    memory_store,
):
    with pytest.raises(TypeError, match="constitution"):
        memory_store.export_versions()
