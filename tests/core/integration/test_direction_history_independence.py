"""Binders with different delivery histories receive the same authoritative direction."""

import pytest

from kyno.sdk import DirectionBinder
from kyno.sdk.client import LocalDirectionSource
from kyno.wire.models import DetailLevel


@pytest.fixture(
    params=[
        pytest.param(DetailLevel.COMPACT, id="same-constitution-version-and-compact-detail"),
        pytest.param(DetailLevel.FULL, id="same-constitution-version-and-full-detail"),
    ]
)
def same_constitution_binders_with_different_last_seen_versions(control_plane, request):
    control_plane.apply_direction(
        mission="Answer support questions",
        principles=["Be clear"],
        constitution_key="support",
        change_note="Initial direction",
    )
    returning_binder = DirectionBinder(
        LocalDirectionSource(control_plane), "support", detail=request.param
    )
    returning_binder.bind()
    control_plane.apply_direction(
        mission="Resolve support requests",
        principles=["Be clear"],
        constitution_key="support",
        change_note="Prioritize resolution",
    )
    new_binder = DirectionBinder(
        LocalDirectionSource(control_plane), "support", detail=request.param
    )
    return returning_binder, new_binder


def test_given_different_last_seen_versions_when_bind_with_status_then_directions_are_equal(
    same_constitution_binders_with_different_last_seen_versions,
):
    returning_binder, new_binder = same_constitution_binders_with_different_last_seen_versions

    returning = returning_binder.bind_with_status()
    first_visit = new_binder.bind_with_status()

    assert returning.direction == first_visit.direction


def test_given_different_last_seen_versions_when_direction_render_then_blocks_are_equal(
    same_constitution_binders_with_different_last_seen_versions,
):
    returning_binder, new_binder = same_constitution_binders_with_different_last_seen_versions
    returning = returning_binder.bind_with_status()
    first_visit = new_binder.bind_with_status()

    returning_block = returning.direction.render()
    first_visit_block = first_visit.direction.render()

    assert returning_block == first_visit_block


def test_given_different_last_seen_versions_when_direction_to_dict_then_payloads_are_equal(
    same_constitution_binders_with_different_last_seen_versions,
):
    returning_binder, new_binder = same_constitution_binders_with_different_last_seen_versions
    returning = returning_binder.bind_with_status()
    first_visit = new_binder.bind_with_status()

    returning_payload = returning.direction.to_dict()
    first_visit_payload = first_visit.direction.to_dict()

    assert returning_payload == first_visit_payload


def test_given_different_last_seen_versions_when_bind_with_status_then_notes_match_each_history(
    same_constitution_binders_with_different_last_seen_versions,
):
    returning_binder, new_binder = same_constitution_binders_with_different_last_seen_versions

    returning = returning_binder.bind_with_status()
    first_visit = new_binder.bind_with_status()

    assert returning.change_notes == ("Prioritize resolution",)
    assert first_visit.change_notes == ("Initial direction", "Prioritize resolution")


def test_given_different_last_seen_versions_when_bind_with_status_then_delta_matches_each_history(
    same_constitution_binders_with_different_last_seen_versions,
):
    returning_binder, new_binder = same_constitution_binders_with_different_last_seen_versions

    returning = returning_binder.bind_with_status()
    first_visit = new_binder.bind_with_status()

    assert returning.delta == (
        'The mission was "Answer support questions" and is now "Resolve support requests".',
    )
    assert first_visit.delta == ()
