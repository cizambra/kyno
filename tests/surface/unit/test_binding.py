import json
from dataclasses import FrozenInstanceError

import pytest

from kyno.sdk.binding import BindingStatus, DirectionBinding
from kyno.sdk.cell import Direction


@pytest.mark.parametrize("status", ["pulled", "cached", "empty"])
def test_given_a_status_string_when_constructing_a_binding_then_it_becomes_an_enum(status):
    binding = DirectionBinding(Direction.empty("sales"), status)
    assert binding.status is BindingStatus(status)
    assert json.loads(json.dumps(binding.status)) == status


@pytest.mark.parametrize("status", ["fresh", "current"])
def test_given_an_unknown_status_when_constructing_a_binding_then_it_is_rejected(status):
    with pytest.raises(ValueError):
        DirectionBinding(Direction.empty("sales"), status)


@pytest.mark.parametrize("field", ["direction", "status", "recording"])
def test_given_DirectionBinding_when_reassigning_a_field_then_FrozenInstanceError_is_raised(field):
    binding = DirectionBinding(Direction.empty("sales"), BindingStatus.EMPTY)
    with pytest.raises(FrozenInstanceError):
        setattr(binding, field, None)
