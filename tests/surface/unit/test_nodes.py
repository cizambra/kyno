from unittest.mock import Mock

import pytest

from kyno.adapters.langgraph.nodes import (
    direction_from_state,
    direction_node,
    direction_update,
    pull_before,
)
from kyno.sdk.binding import BindingStatus, DirectionBinding
from kyno.sdk.cell import Direction


@pytest.mark.parametrize(
    "direction_fields",
    [
        pytest.param({"kyno_version": 0}, id="zero-version"),
        pytest.param({"kyno_version": 3}, id="written-version"),
        pytest.param({"kyno_mission": "Help customers"}, id="mission"),
        pytest.param({"kyno_declaration": "Explain decisions"}, id="declaration"),
        pytest.param({"kyno_principles": []}, id="principles"),
        pytest.param({"kyno_change_notes": []}, id="change-notes"),
        pytest.param({"kyno_delta": []}, id="delta"),
        pytest.param({"kyno_detail": "compact"}, id="detail"),
        pytest.param({"kyno_direction": "Saved block"}, id="rendered-direction"),
        pytest.param({"kyno_binding_status": "pulled"}, id="binding-status"),
        pytest.param({"kyno_recording": None}, id="recording"),
    ],
)
def test_given_direction_without_identity_when_direction_from_state_then_missing_key_is_rejected(
    direction_fields,
):
    with pytest.raises(ValueError, match="kyno_constitution_key"):
        direction_from_state(direction_fields)


def test_given_messages_only_when_direction_from_state_then_version_zero_has_no_constitution_key():
    state = {"messages": ["Hello"]}

    direction = direction_from_state(state)

    assert direction.constitution_key is None
    assert direction.version == 0
    assert direction.mission == ""


@pytest.mark.parametrize(
    "key",
    [None, 1, True, [], {}, "", " ", "Upper", "bad/name", "two words", "a" * 201],
    ids=[
        "null",
        "integer",
        "boolean",
        "list",
        "object",
        "empty",
        "blank",
        "uppercase",
        "slash",
        "space",
        "oversized",
    ],
)
def test_given_invalid_saved_key_when_direction_from_state_runs_then_key_is_rejected(key):
    state = {"kyno_constitution_key": key, "kyno_version": 3, "kyno_mission": "Help customers"}

    with pytest.raises(ValueError, match="constitution key"):
        direction_from_state(state)


@pytest.mark.parametrize("key", ["support", "a" * 200], ids=["named", "maximum-length"])
def test_given_padded_saved_key_when_direction_from_state_runs_then_trimmed_key_returns(key):
    state = {"kyno_constitution_key": f" \t{key}\n", "kyno_version": 3}

    direction = direction_from_state(state)

    assert direction.constitution_key == key
    assert state["kyno_constitution_key"] == f" \t{key}\n"


def test_given_empty_state_when_direction_from_state_then_version_zero_has_no_constitution_key():
    direction = direction_from_state({})

    assert direction.constitution_key is None
    assert direction.version == 0
    assert direction.mission == ""


def test_given_transition_metadata_when_direction_update_then_state_contains_supplied_metadata():
    direction = Direction.empty("support")

    update = direction_update(
        direction,
        change_notes=("Support became the priority",),
        delta=("Mission changed.",),
    )

    assert update["kyno_change_notes"] == ["Support became the priority"]
    assert update["kyno_delta"] == ["Mission changed."]


def test_given_no_transition_metadata_when_direction_update_then_state_metadata_is_empty():
    direction = Direction.empty("support")

    update = direction_update(direction)

    assert update["kyno_change_notes"] == []
    assert update["kyno_delta"] == []


def test_given_binding_metadata_when_direction_node_runs_then_state_contains_binding_metadata():
    binding = DirectionBinding(
        Direction.empty("support"),
        BindingStatus.PULLED,
        change_notes=("Support became the priority",),
        delta=("Mission changed.",),
    )
    binder = Mock(bind_with_status=Mock(return_value=binding))
    node = direction_node(binder)

    update = node({})

    assert update["kyno_change_notes"] == ["Support became the priority"]
    assert update["kyno_delta"] == ["Mission changed."]


def test_given_binding_metadata_when_pull_before_runs_then_wrapped_node_receives_binding_metadata():
    binding = DirectionBinding(
        Direction.empty("support"),
        BindingStatus.PULLED,
        change_notes=("Support became the priority",),
        delta=("Mission changed.",),
    )
    binder = Mock(bind_with_status=Mock(return_value=binding))
    work_node = Mock(return_value={})
    wrapped = pull_before(binder)(work_node)

    wrapped({})

    received_state = work_node.call_args.args[0]
    assert received_state["kyno_change_notes"] == ["Support became the priority"]
    assert received_state["kyno_delta"] == ["Mission changed."]


def test_given_binding_metadata_when_pull_before_runs_then_result_contains_binding_metadata():
    binding = DirectionBinding(
        Direction.empty("support"),
        BindingStatus.PULLED,
        change_notes=("Support became the priority",),
        delta=("Mission changed.",),
    )
    binder = Mock(bind_with_status=Mock(return_value=binding))
    wrapped = pull_before(binder)(lambda state: {})

    update = wrapped({})

    assert update["kyno_change_notes"] == ["Support became the priority"]
    assert update["kyno_delta"] == ["Mission changed."]


@pytest.mark.parametrize("status", [BindingStatus.PULLED, BindingStatus.EMPTY])
def test_given_old_state_metadata_when_direction_node_runs_then_empty_binding_clears_metadata(
    status,
):
    binding = DirectionBinding(Direction.empty("support"), status)
    binder = Mock(bind_with_status=Mock(return_value=binding))
    node = direction_node(binder)
    state = {
        "kyno_change_notes": ["Prioritize customer support"],
        "kyno_delta": ["Mission changed."],
    }

    update = node(state)

    assert update["kyno_change_notes"] == []
    assert update["kyno_delta"] == []


@pytest.mark.parametrize("status", [BindingStatus.PULLED, BindingStatus.EMPTY])
def test_given_old_state_metadata_when_pull_before_runs_then_work_receives_empty_metadata(status):
    binding = DirectionBinding(Direction.empty("support"), status)
    binder = Mock(bind_with_status=Mock(return_value=binding))
    work_node = Mock(return_value={})
    wrapped = pull_before(binder)(work_node)
    state = {
        "kyno_change_notes": ["Prioritize customer support"],
        "kyno_delta": ["Mission changed."],
    }

    wrapped(state)

    received_state = work_node.call_args.args[0]
    assert received_state["kyno_change_notes"] == []
    assert received_state["kyno_delta"] == []


def test_given_binding_metadata_when_state_lists_are_edited_then_binding_metadata_is_unchanged():
    binding = DirectionBinding(
        Direction.empty("support"),
        BindingStatus.PULLED,
        change_notes=("Prioritize customer support",),
        delta=("Mission changed.",),
    )
    binder = Mock(bind_with_status=Mock(return_value=binding))
    state = direction_node(binder)({})

    state["kyno_change_notes"].append("Caller annotation")
    state["kyno_delta"].clear()

    assert binding.change_notes == ("Prioritize customer support",)
    assert binding.delta == ("Mission changed.",)


def test_given_same_direction_fields_when_direction_from_state_then_delivery_metadata_is_ignored():
    authoritative_state = {
        "kyno_constitution_key": "support",
        "kyno_version": 2,
        "kyno_mission": "Resolve support requests",
        "kyno_principles": [{"title": "Be clear", "description": ""}],
    }
    first_state = {
        **authoritative_state,
        "kyno_change_notes": ["Initial direction", "Prioritize resolution"],
        "kyno_delta": [],
    }
    returning_state = {
        **authoritative_state,
        "kyno_change_notes": ["Prioritize resolution"],
        "kyno_delta": ["Mission changed."],
    }

    first_direction = direction_from_state(first_state)
    returning_direction = direction_from_state(returning_state)

    assert first_direction == returning_direction
