import json
from dataclasses import FrozenInstanceError

import pytest

from kyno.sdk.binding import DeliveryStatus, DirectionBinding
from kyno.sdk.cell import Direction


@pytest.mark.parametrize("status", ["current", "cached", "empty"])
def test_given_a_status_string_when_constructing_a_binding_then_it_becomes_an_enum(status):
    binding = DirectionBinding(Direction.empty("sales"), status)
    assert binding.status is DeliveryStatus(status)
    assert json.loads(json.dumps(binding.status)) == status


def test_given_an_unknown_status_when_constructing_a_binding_then_it_is_rejected():
    with pytest.raises(ValueError):
        DirectionBinding(Direction.empty("sales"), "fresh")


@pytest.mark.parametrize("field", ["direction", "status"])
def test_given_a_binding_when_reassigning_a_field_then_it_is_immutable(field):
    binding = DirectionBinding(Direction.empty("sales"), DeliveryStatus.EMPTY)
    with pytest.raises(FrozenInstanceError):
        setattr(binding, field, None)
