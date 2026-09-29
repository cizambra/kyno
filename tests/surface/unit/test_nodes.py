import pytest

from kyno.adapters.langgraph.nodes import direction_from_state


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
