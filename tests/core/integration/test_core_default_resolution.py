"""Core resolves omitted selectors consistently across its direction operations."""

import pytest

from kyno.delivery_recording import DeliveryRecorder
from kyno.service import ControlPlane
from kyno.store.delivery_record import SqlDeliveryRecordStore


@pytest.fixture(params=[{}, {"constitution_key": None}], ids=["omitted", "explicit-none"])
def selection(request):
    return request.param


def test_given_no_constitution_key_when_current_then_default_direction_returns(
    memory_store, selection
):
    plane = ControlPlane(memory_store)
    plane.apply_direction(
        constitution_key="default", mission="Default mission", change_note="Initial"
    )
    plane.apply_direction(
        constitution_key="support", mission="Support mission", change_note="Initial"
    )

    direction = plane.current(**selection)

    assert direction.constitution_key == "default"
    assert direction.version == 1
    assert direction.mission == "Default mission"


def test_given_no_constitution_key_when_get_constitution_version_zero_then_default_is_empty(
    memory_store, selection
):
    plane = ControlPlane(memory_store)
    plane.apply_direction(
        constitution_key="default", mission="Default mission", change_note="Initial"
    )
    plane.apply_direction(
        constitution_key="support", mission="Support mission", change_note="Initial"
    )

    direction = plane.get_constitution(version=0, **selection)

    assert direction.constitution_key == "default"
    assert direction.version == 0
    assert direction.mission == ""


def test_given_public_default_and_private_support_when_publication_then_default_is_public(
    memory_store, selection
):
    plane = ControlPlane(memory_store)
    plane.apply_direction(
        constitution_key="default", mission="Default mission", change_note="Initial"
    )
    plane.apply_direction(
        constitution_key="support", mission="Support mission", change_note="Initial"
    )
    plane.publish("default")

    publication = plane.publication(**selection)

    assert publication.constitution_key == "default"
    assert publication.published


def test_given_public_constitutions_when_public_constitution_then_default_direction_returns(
    memory_store, selection
):
    plane = ControlPlane(memory_store)
    plane.apply_direction(
        constitution_key="default", mission="Default mission", change_note="Initial"
    )
    plane.apply_direction(
        constitution_key="support", mission="Support mission", change_note="Initial"
    )
    plane.publish("default")
    plane.publish("support")

    direction = plane.public_constitution(**selection)

    assert direction.constitution_key == "default"
    assert direction.mission == "Default mission"


@pytest.mark.parametrize("arguments", [{}, {"constitution_key": None}], ids=["omitted", "null"])
def test_given_no_constitution_key_when_record_delivery_then_stored_record_identifies_default(
    memory_store, arguments
):
    history = SqlDeliveryRecordStore(memory_store.engine)
    plane = ControlPlane(memory_store, delivery_recorder=DeliveryRecorder(history, "always"))
    current = plane.apply_direction(
        constitution_key="default", mission="Default mission", change_note="Initial"
    )

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
