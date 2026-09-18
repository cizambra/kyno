"""Core resolves omitted selectors consistently across its direction operations."""

import pytest

from kyno.service import ControlPlane


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
        ("publish", {}),
        ("unpublish", {}),
        ("public_constitution", {}),
    ],
)
def test_given_omitted_selection_when_calling_core_then_result_matches_explicit_default(
    memory_store, selector, operation, arguments
):
    plane = ControlPlane(memory_store)
    plane.apply_direction(mission="Default", change_note="init", constitution_key="default")
    plane.apply_direction(mission="Other", change_note="init", constitution_key="support")
    plane.publish(constitution_key="default")
    expected = getattr(plane, operation)(constitution_key="default", **arguments)

    assert getattr(plane, operation)(**selector, **arguments) == expected
