"""Binder behavior against a real control plane."""

from kyno.sdk.binder import DirectionBinder
from kyno.sdk.cell import FULL
from kyno.sdk.client import LocalDirectionSource


def test_given_a_step_when_binding_then_the_current_version_is_bound(control_plane):
    control_plane.set_direction(mission="M1", change_note="init")
    binder = DirectionBinder(LocalDirectionSource(control_plane))

    direction = binder.bind()
    assert direction.version == 1 and direction.mission == "M1"
    assert direction.constitution == "default"


def test_given_a_direction_change_between_steps_when_binding_the_second_then_it_sees_the_change(
    control_plane,
):
    control_plane.set_direction(mission="M1", change_note="init")
    binder = DirectionBinder(LocalDirectionSource(control_plane))
    first = binder.bind()

    control_plane.set_direction(mission="M2", change_note="pivot")
    second = binder.bind()

    assert (first.version, first.mission) == (1, "M1")
    assert (second.version, second.mission) == (2, "M2")


def test_given_a_context_choice_when_binding_then_only_the_injected_block_changes(control_plane):
    # The knob is about what an agent is sent at every step, never about what
    # the control plane holds or answers.
    control_plane.set_direction(
        mission="M1",
        declaration="The long form.",
        principles=({"title": "Be honest", "description": "Say the hard number first."},),
        change_note="init",
    )
    source = LocalDirectionSource(control_plane)
    compact = DirectionBinder(source).bind()
    full = DirectionBinder(source, context=FULL).bind()

    assert "The long form." not in compact.render()
    assert "The long form." in full.render()
    assert compact.declaration == full.declaration == "The long form."
    assert compact.principles == full.principles
