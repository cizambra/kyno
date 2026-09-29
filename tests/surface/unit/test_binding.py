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


def test_given_an_unknown_status_when_constructing_a_binding_then_it_is_rejected():
    with pytest.raises(ValueError):
        DirectionBinding(Direction.empty("sales"), "fresh")


@pytest.mark.parametrize("field", ["direction", "status", "recording", "change_notes", "delta"])
def test_given_DirectionBinding_when_reassigning_a_field_then_FrozenInstanceError_is_raised(field):
    binding = DirectionBinding(Direction.empty("sales"), BindingStatus.EMPTY)
    with pytest.raises(FrozenInstanceError):
        setattr(binding, field, None)


def test_given_transition_metadata_when_DirectionBinding_then_metadata_is_available():
    direction = Direction.empty("support")

    binding = DirectionBinding(
        direction,
        BindingStatus.PULLED,
        change_notes=("Support became the priority",),
        delta=("Mission changed.",),
    )

    assert binding.change_notes == ("Support became the priority",)
    assert binding.delta == ("Mission changed.",)


def test_given_no_transition_metadata_when_DirectionBinding_then_metadata_is_empty():
    binding = DirectionBinding(Direction.empty("support"), BindingStatus.EMPTY)

    assert binding.change_notes == ()
    assert binding.delta == ()


def test_given_metadata_lists_when_DirectionBinding_then_later_list_edits_do_not_change_binding():
    notes = ["Support became the priority"]
    delta = ["Mission changed."]

    binding = DirectionBinding(
        Direction.empty("support"), BindingStatus.PULLED, change_notes=notes, delta=delta
    )
    notes.append("Another change")
    delta.clear()

    assert binding.change_notes == ("Support became the priority",)
    assert binding.delta == ("Mission changed.",)
