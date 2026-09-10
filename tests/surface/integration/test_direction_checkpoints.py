"""LangGraph preserves the direction and delivery status supplied to each work node."""

from operator import add
from types import SimpleNamespace
from typing import Annotated
from unittest.mock import Mock

import pytest

pytest.importorskip("langgraph")

from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402
from langgraph.graph import END, START, StateGraph  # noqa: E402

from kyno.adapters.langgraph import (  # noqa: E402
    KynoState,
    direction_node,
    direction_update,
    pull_before,
)
from kyno.sdk import DeliveryStatus, DirectionBinder, PullPolicy  # noqa: E402
from kyno.sdk.cell import Direction  # noqa: E402
from kyno.sdk.errors import KynoUnavailableError  # noqa: E402
from kyno.wire.models import ChangesSince, DetailLevel  # noqa: E402


class ReceiptState(KynoState, total=False):
    receipts: Annotated[list[dict], add]


@pytest.fixture
def source():
    return SimpleNamespace(
        changes_since=Mock(
            return_value=ChangesSince(
                current_version=2,
                changed=True,
                mission="Help customers",
                principles=("Be honest",),
                changed_mission=True,
                changed_principles=True,
                change_notes=("Prioritize lasting fixes",),
                declaration="Explain the full resolution.",
                delta=("Mission changed.",),
            )
        )
    )


def receipt(state):
    return {"receipts": [{key: value for key, value in state.items() if key.startswith("kyno_")}]}


@pytest.mark.parametrize("wrapper", [False, True], ids=["direction-node", "pull-before"])
@pytest.mark.parametrize("status", list(DeliveryStatus))
@pytest.mark.parametrize("context", list(DetailLevel))
def test_given_a_binding_when_work_is_checkpointed_then_its_exact_direction_and_status_survive(
    source, wrapper, status, context
):
    binder = DirectionBinder(source, context=context)
    if status is DeliveryStatus.CACHED:
        binder.bind("support")
    if status is not DeliveryStatus.CURRENT:
        source.changes_since.side_effect = OSError("offline")
    source.changes_since.reset_mock()
    graph = StateGraph(ReceiptState)
    if wrapper:
        graph.add_node("work", pull_before(binder, "support")(receipt)).add_edge(START, "work")
    else:
        graph.add_node("pull", direction_node(binder, "support")).add_node("work", receipt)
        graph.add_edge(START, "pull").add_edge("pull", "work")
    app = graph.add_edge("work", END).compile(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "delivery"}}

    result = app.invoke({}, config)
    restored = app.get_state(config).values

    assert source.changes_since.call_count == 1
    assert restored == result
    assert restored["kyno_delivery_status"] == status.value
    assert type(restored["kyno_delivery_status"]) is str
    assert restored["receipts"][0]["kyno_delivery_status"] == status.value
    assert restored["receipts"][0]["kyno_direction"] == restored["kyno_direction"]
    assert restored["kyno_constitution"] == "support"
    if status is DeliveryStatus.EMPTY:
        expected = Direction.empty("support", context)
    else:
        expected = Direction.from_changes(source.changes_since.return_value, "support", context)
    assert restored["kyno_direction"] == expected.render()


def test_given_checkpointed_direction_when_resuming_without_a_pull_then_its_status_is_unchanged(
    source,
):
    binder = DirectionBinder(source)
    app = (
        StateGraph(ReceiptState)
        .add_node("pull", direction_node(binder))
        .add_node("work", receipt)
        .add_edge(START, "pull")
        .add_edge("pull", "work")
        .add_edge("work", END)
        .compile(checkpointer=InMemorySaver(), interrupt_before=["work"])
    )
    config = {"configurable": {"thread_id": "resume"}}
    paused = app.invoke({}, config)
    source.changes_since.side_effect = OSError("offline")

    resumed = app.invoke(None, config)

    assert source.changes_since.call_count == 1
    assert resumed["receipts"][0]["kyno_delivery_status"] == "current"
    assert resumed["receipts"][0]["kyno_direction"] == paused["kyno_direction"]


def test_given_two_current_step_receipts_when_next_pull_fails_then_only_new_receipt_is_cached(
    source,
):
    binder = DirectionBinder(source)

    def disconnect(state):
        source.changes_since.side_effect = OSError("offline")
        return {}

    app = (
        StateGraph(ReceiptState)
        .add_node("pull", direction_node(binder))
        .add_node("first", receipt)
        .add_node("second", receipt)
        .add_node("disconnect", disconnect)
        .add_node("fallback", pull_before(binder)(receipt))
        .add_edge(START, "pull")
        .add_edge("pull", "first")
        .add_edge("pull", "second")
        .add_edge(["first", "second"], "disconnect")
        .add_edge("disconnect", "fallback")
        .add_edge("fallback", END)
        .compile(checkpointer=InMemorySaver())
    )

    result = app.invoke({}, {"configurable": {"thread_id": "fan-out"}})

    first, second, fallback = result["receipts"]
    assert first == second
    assert first["kyno_delivery_status"] == "current"
    assert fallback["kyno_delivery_status"] == "cached"
    assert fallback["kyno_direction"] == first["kyno_direction"]
    assert source.changes_since.call_count == 2


def test_given_current_status_when_direction_lacks_metadata_then_checkpoint_status_is_unknown():
    app = (
        StateGraph(ReceiptState)
        .add_node(
            "manual_direction",
            lambda state: direction_update(
                Direction(constitution="support", version=2, mission="Help", principles=())
            ),
        )
        .add_edge(START, "manual_direction")
        .add_edge("manual_direction", END)
        .compile(checkpointer=InMemorySaver())
    )
    config = {"configurable": {"thread_id": "unknown"}}

    app.invoke({"kyno_delivery_status": "current"}, config)

    assert app.get_state(config).values["kyno_delivery_status"] is None


def test_given_state_without_delivery_metadata_when_work_runs_then_no_current_status_is_invented():
    app = (
        StateGraph(ReceiptState)
        .add_node("work", receipt)
        .add_edge(START, "work")
        .add_edge("work", END)
        .compile(checkpointer=InMemorySaver())
    )

    result = app.invoke({}, {"configurable": {"thread_id": "missing"}})

    assert "kyno_delivery_status" not in result
    assert "kyno_delivery_status" not in result["receipts"][0]


@pytest.mark.parametrize("cached", [False, True])
def test_given_fail_closed_when_the_pull_fails_then_the_wrapped_work_does_not_run(source, cached):
    binder = DirectionBinder(source, policy=PullPolicy(fail_closed=True))
    if cached:
        binder.bind()
    source.changes_since.side_effect = OSError("offline")
    work = Mock()
    app = (
        StateGraph(ReceiptState)
        .add_node("work", pull_before(binder)(work))
        .add_edge(START, "work")
        .add_edge("work", END)
        .compile()
    )

    with pytest.raises(KynoUnavailableError):
        app.invoke({})

    work.assert_not_called()
