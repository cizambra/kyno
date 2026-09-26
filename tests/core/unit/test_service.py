from unittest.mock import Mock

import pytest

from kyno.service import ControlPlane


@pytest.mark.parametrize(
    "operation, arguments",
    [
        ("current", {}),
        ("get_constitution", {"version": 0}),
        ("changes_since", {"last_seen_version": 0}),
        ("publication", {}),
        ("publish", {}),
        ("unpublish", {}),
        ("public_constitution", {}),
        ("export_versions", {}),
        ("apply_direction", {"mission": "Help", "change_note": "init"}),
        ("preview_edit", {"mission": "Help"}),
        ("head_and_delta", {"mission": "Help"}),
    ],
)
def test_given_constitution_keyword_when_core_method_receives_it_then_type_error_precedes_storage(
    operation, arguments
):
    store = Mock()
    plane = ControlPlane(store)

    with pytest.raises(TypeError, match="unexpected keyword argument 'constitution'"):
        getattr(plane, operation)(constitution="support", **arguments)

    assert store.mock_calls == []
