"""Delivery receipts survive LangGraph checkpoints and remain paired with supplied direction."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

pytest.importorskip("langgraph")

from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402
from langgraph.graph import END, START, StateGraph  # noqa: E402

from kyno.adapters.langgraph import KynoState, direction_node  # noqa: E402
from kyno.sdk import (  # noqa: E402
    DeliveryStatus,
    DirectionBinder,
    DirectionResponse,
    RecordingReceipt,
)
from kyno.wire.models import ChangesSince  # noqa: E402


class RecordedState(KynoState, total=False):
    answer_record: dict


@pytest.mark.parametrize("recording_status", ["recorded", "disabled", "failed", None])
@pytest.mark.parametrize("delivery_status", list(DeliveryStatus))
def test_given_a_delivery_receipt_when_a_checkpoint_resumes_then_work_keeps_the_same_receipt(
    recording_status, delivery_status
):
    receipt = (
        RecordingReceipt(
            status=recording_status,
            record_id="delivery-1" if recording_status == "recorded" else None,
        )
        if recording_status is not None
        else None
    )
    source = SimpleNamespace(
        changes_since=Mock(
            return_value=DirectionResponse(
                changes=ChangesSince(1, True, "Help customers", (), True, False, ("init",)),
                recording=receipt,
            )
        )
    )
    binder = DirectionBinder(source)
    if delivery_status is DeliveryStatus.CACHED:
        binder.bind()
    if delivery_status is not DeliveryStatus.CURRENT:
        source.changes_since.side_effect = OSError("offline")
    source.changes_since.reset_mock()

    def answer(state):
        return {
            "answer_record": {
                "recording": state["kyno_recording"],
                "direction": state["kyno_direction"],
                "output": "An answer",
            }
        }

    graph = (
        StateGraph(RecordedState)
        .add_node("pull", direction_node(binder))
        .add_node("answer", answer)
        .add_edge(START, "pull")
        .add_edge("pull", "answer")
        .add_edge("answer", END)
        .compile(checkpointer=InMemorySaver(), interrupt_before=["answer"])
    )
    config = {"configurable": {"thread_id": "support-run"}}
    graph.invoke({"kyno_recording": {"status": "recorded", "record_id": "old"}}, config)
    saved = graph.get_state(config).values
    expected = (
        {"status": receipt.status.value, "record_id": receipt.record_id}
        if receipt is not None and delivery_status is not DeliveryStatus.EMPTY
        else None
    )

    assert saved["kyno_recording"] == expected
    assert saved["kyno_delivery_status"] is delivery_status
    result = graph.invoke(None, config)

    assert result["answer_record"] == {
        "recording": expected,
        "direction": saved["kyno_direction"],
        "output": "An answer",
    }
    assert result["kyno_recording"] == expected
    assert source.changes_since.call_count == 1


def test_given_two_reads_of_one_version_when_the_graph_runs_twice_then_receipts_stay_distinct():
    changes = ChangesSince(1, True, "Help customers", (), True, False, ("init",))
    source = SimpleNamespace(
        changes_since=Mock(
            side_effect=[
                DirectionResponse(changes, RecordingReceipt("recorded", "delivery-1")),
                DirectionResponse(changes, RecordingReceipt("recorded", "delivery-2")),
            ]
        )
    )
    graph = (
        StateGraph(KynoState)
        .add_node("pull", direction_node(DirectionBinder(source)))
        .add_edge(START, "pull")
        .add_edge("pull", END)
        .compile(checkpointer=InMemorySaver())
    )
    first_config = {"configurable": {"thread_id": "first"}}
    second_config = {"configurable": {"thread_id": "second"}}

    first = graph.invoke({}, first_config)
    second = graph.invoke({}, second_config)
    second["kyno_recording"]["record_id"] = "edited"

    assert first["kyno_recording"]["record_id"] == "delivery-1"
    assert graph.get_state(first_config).values["kyno_recording"]["record_id"] == "delivery-1"
    assert graph.get_state(second_config).values["kyno_recording"]["record_id"] == "delivery-2"
    assert first["kyno_version"] == second["kyno_version"] == 1
