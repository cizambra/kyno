from unittest.mock import Mock

import pytest

pytest.importorskip("langgraph")

from kyno.adapters import langgraph  # noqa: E402
from kyno.adapters.langgraph import nodes  # noqa: E402
from kyno.sdk.binding import DeliveryStatus, DirectionBinding  # noqa: E402
from kyno.sdk.cell import Direction  # noqa: E402
from kyno.sdk.recording import RecordingReceipt  # noqa: E402


def test_given_langgraph_adapter_when_inspecting_exports_then_only_direction_helpers_are_public():
    assert set(langgraph.__all__) == {
        "KynoState",
        "direction_from_state",
        "direction_node",
        "direction_update",
        "pull_before",
    }
    assert not hasattr(langgraph, "gate_node")
    assert not hasattr(nodes, "gate_node")


def test_given_KynoState_when_direction_update_runs_then_keys_match_declared_fields():
    update = langgraph.direction_update(Direction.empty("support"))
    assert set(langgraph.KynoState.__annotations__) == set(update)


@pytest.mark.parametrize("wrapped", [False, True])
@pytest.mark.parametrize("status", ["recorded", "disabled", "failed", None])
def test_given_receipt_when_direction_node_or_pull_before_runs_then_state_has_recording_copy(
    wrapped, status
):
    record_id = "delivery-1" if status == "recorded" else None
    recording = RecordingReceipt(status=status, record_id=record_id) if status is not None else None
    binding = DirectionBinding(
        direction=Direction.empty("support"),
        status=DeliveryStatus.CURRENT,
        recording=recording,
    )
    binder = Mock(bind_with_status=Mock(return_value=binding))
    captured = []

    def work(state):
        captured.append(state["kyno_recording"])
        return {"output": "answer"}

    node = (
        langgraph.pull_before(binder, "support")(work)
        if wrapped
        else langgraph.direction_node(binder, "support")
    )
    result = node({"kyno_recording": {"status": "recorded", "record_id": "old"}})
    expected = {"status": status, "record_id": record_id} if status is not None else None

    assert result["kyno_recording"] == expected
    assert result["kyno_direction"] == binding.direction.render()
    binder.bind_with_status.assert_called_once_with("support")
    if wrapped:
        assert captured == [expected]
    if recording is not None:
        result["kyno_recording"]["record_id"] = "edited"
        assert recording.record_id == record_id


def test_given_no_receipt_when_direction_update_runs_then_kyno_recording_is_none():
    update = langgraph.direction_update(Direction.empty("support"))

    assert update["kyno_recording"] is None
