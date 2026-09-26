import pytest

from kyno.adapters.langgraph.nodes import direction_from_state


@pytest.mark.parametrize("current_key", [None, "support", "sales"])
def test_given_unsupported_checkpoint_key_when_direction_from_state_then_migration_error(
    current_key,
):
    state = {
        "kyno_constitution": "support",
        "kyno_version": 3,
        "kyno_mission": "Help customers",
    }
    if current_key is not None:
        state["kyno_constitution_key"] = current_key

    with pytest.raises(ValueError, match="migrate.*checkpoint"):
        direction_from_state(state)

    assert state["kyno_constitution"] == "support"
    assert state["kyno_mission"] == "Help customers"


@pytest.mark.parametrize(
    "direction_fields",
    [{"kyno_version": 0}, {"kyno_version": 3}, {"kyno_mission": "Help customers"}],
)
def test_given_direction_without_identity_when_direction_from_state_then_missing_key_is_rejected(
    direction_fields,
):
    with pytest.raises(ValueError, match="kyno_constitution_key"):
        direction_from_state(direction_fields)


def test_given_application_state_when_direction_from_state_then_unresolved_version_zero_returns():
    direction = direction_from_state({"messages": ["Hello"]})

    assert direction.constitution_key is None
    assert direction.version == 0
    assert direction.mission == ""
