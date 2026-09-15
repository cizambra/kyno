import pytest

pytest.importorskip("langgraph")

from kyno.adapters import langgraph  # noqa: E402
from kyno.adapters.langgraph import nodes  # noqa: E402
from kyno.sdk.cell import Direction  # noqa: E402


def test_given_the_adapter_when_inspecting_exports_then_it_supplies_direction_helpers():
    assert set(langgraph.__all__) == {
        "KynoState",
        "direction_from_state",
        "direction_node",
        "direction_update",
        "pull_before",
    }
    assert not hasattr(langgraph, "gate_node")
    assert not hasattr(nodes, "gate_node")


def test_given_direction_state_when_inspecting_fields_then_it_declares_only_direction():
    update = langgraph.direction_update(Direction.empty("support"))
    assert set(langgraph.KynoState.__annotations__) == set(update)
