"""LangGraph preserves the direction and delivery status supplied to each work node."""

import json
from dataclasses import replace
from operator import add
from types import SimpleNamespace
from typing import Annotated
from unittest.mock import Mock

import pytest

from tests.paths import REPO_ROOT

pytest.importorskip("langgraph")

from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402
from langgraph.graph import END, START, StateGraph  # noqa: E402

from kyno.adapters.langgraph import (  # noqa: E402
    KynoState,
    direction_from_state,
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


@pytest.fixture
def documented_support_graph(source):
    guide = (REPO_ROOT / "docs/langgraph.md").read_text()
    answer_section = guide.split("## Required integration", 1)[1]
    answer_code = answer_section.split("```python\n", 1)[1].split("```", 1)[0]
    checkpoint_section = guide.split("### Optional: LangGraph checkpoints", 1)[1]
    checkpoint_code = checkpoint_section.split("```python\n", 1)[1].split("```", 1)[0]
    namespace = {
        "binder": DirectionBinder(
            source, context=DetailLevel.FULL, policy=PullPolicy(fail_closed=True)
        ),
        "model": SimpleNamespace(invoke=Mock(return_value=SimpleNamespace(content="Test reply"))),
    }
    exec(compile(answer_code, "docs/langgraph.md", "exec"), namespace)
    return namespace, checkpoint_code


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
    assert restored["kyno_delivery_status"] is status
    assert restored["receipts"][0]["kyno_delivery_status"] is status
    serialized = json.loads(json.dumps(restored))
    assert serialized["kyno_delivery_status"] == status.value
    assert type(serialized["kyno_delivery_status"]) is str
    assert restored["receipts"][0]["kyno_direction"] == restored["kyno_direction"]
    assert restored["kyno_constitution"] == "support"
    if status is DeliveryStatus.EMPTY:
        expected = Direction.empty("support", context)
    else:
        expected = Direction.from_changes(source.changes_since.return_value, "support", context)
    assert restored["kyno_direction"] == expected.render()
    assert direction_from_state(restored) == expected
    assert direction_from_state(restored["receipts"][0]) == expected
    normalized = direction_update(
        direction_from_state(serialized), status=serialized["kyno_delivery_status"]
    )
    assert normalized["kyno_delivery_status"] is status


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
    assert resumed["receipts"][0]["kyno_delivery_status"] is DeliveryStatus.CURRENT
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
@pytest.mark.parametrize("wrapper", [False, True], ids=["direction-node", "pull-before"])
def test_given_fail_closed_when_the_pull_fails_then_downstream_work_does_not_run(
    source, cached, wrapper
):
    binder = DirectionBinder(source, policy=PullPolicy(fail_closed=True))
    if cached:
        binder.bind()
    source.changes_since.side_effect = OSError("offline")
    work = Mock()
    graph = StateGraph(ReceiptState)
    if wrapper:
        graph.add_node("work", pull_before(binder)(work)).add_edge(START, "work")
    else:
        graph.add_node("pull", direction_node(binder)).add_node("work", work)
        graph.add_edge(START, "pull").add_edge("pull", "work")
    app = graph.add_edge("work", END).compile()

    with pytest.raises(KynoUnavailableError):
        app.invoke({})

    work.assert_not_called()


@pytest.mark.parametrize("wrapper", [False, True], ids=["direction-node", "pull-before"])
@pytest.mark.parametrize("failed_read", [False, True], ids=["unchanged", "recovered"])
def test_given_the_same_version_when_read_succeeds_then_new_step_status_is_saved_as_current(
    source, wrapper, failed_read
):
    initial = source.changes_since.return_value
    unchanged = replace(
        initial,
        changed=False,
        changed_mission=False,
        changed_principles=False,
        change_notes=(),
        delta=(),
    )
    replies = [initial, OSError("offline"), unchanged] if failed_read else [initial, unchanged]
    source.changes_since.side_effect = replies
    binder = DirectionBinder(source)
    graph = StateGraph(ReceiptState)
    if wrapper:
        graph.add_node("work", pull_before(binder)(receipt)).add_edge(START, "work")
    else:
        graph.add_node("pull", direction_node(binder)).add_node("work", receipt)
        graph.add_edge(START, "pull").add_edge("pull", "work")
    app = graph.add_edge("work", END).compile(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "same-version"}}
    first = app.invoke({}, config)
    first_block = first["kyno_direction"]
    if failed_read:
        fallback = app.invoke({}, config)
        assert fallback["kyno_delivery_status"] == "cached"

    result = app.invoke({}, config)
    saved = app.get_state(config).values

    assert saved == result
    assert saved["kyno_version"] == 2
    assert saved["kyno_delivery_status"] == "current"
    assert saved["kyno_direction"] == Direction.from_changes(unchanged, "default").render()
    assert direction_from_state(saved) == Direction.from_changes(unchanged, "default")
    assert direction_from_state(saved["receipts"][0]) == Direction.from_changes(initial, "default")
    assert saved["receipts"][0]["kyno_direction"] == first_block
    assert saved["receipts"][0]["kyno_delivery_status"] == "current"
    assert saved["receipts"][-1]["kyno_direction"] == saved["kyno_direction"]
    assert saved["receipts"][-1]["kyno_delivery_status"] == "current"
    if failed_read:
        assert saved["receipts"][1]["kyno_delivery_status"] == "cached"
        assert saved["receipts"][1]["kyno_direction"] == first_block
        assert fallback["kyno_delivery_status"] == "cached"
    assert len(saved["receipts"]) == len(replies)
    assert source.changes_since.call_count == len(replies)


def test_given_documented_support_when_checkpointed_then_model_input_matches_the_runnable_example(
    source, example, documented_support_graph, capsys
):
    namespace, checkpoint_code = documented_support_graph

    exec(compile(checkpoint_code, "docs/langgraph.md", "exec"), namespace)

    assert source.changes_since.call_count == 1
    assert namespace["saved"]["kyno_delivery_status"] is DeliveryStatus.CURRENT
    assert namespace["saved"]["kyno_version"] == 2
    assert namespace["saved"]["kyno_context"] is DetailLevel.FULL
    namespace["model"].invoke.assert_called_once_with(example.prepare_messages(namespace["saved"]))
    assert capsys.readouterr().out == (
        "Saved direction version: 2\nDelivery status at that step: current\n"
        "Saved answer: Test reply\n"
    )

    source.changes_since.return_value = replace(
        source.changes_since.return_value, current_version=3, mission="Prioritize lasting fixes"
    )
    updated = namespace["graph"].invoke({}, namespace["config"])
    calls = namespace["model"].invoke.call_args_list

    assert source.changes_since.call_count == 2
    assert len(calls) == 2
    assert updated["kyno_version"] == 3
    assert calls[1].args[0] == example.prepare_messages(updated)
    assert calls[0].args[0][1] == calls[1].args[0][1]
    assert calls[0].args[0][0] != calls[1].args[0][0]
    assert namespace["saved"]["kyno_version"] == 2


@pytest.mark.parametrize("read_fails", [False, True], ids=["unwritten", "unavailable"])
def test_given_missing_direction_when_documented_support_runs_then_the_model_is_not_called(
    source, documented_support_graph, read_fails
):
    namespace, checkpoint_code = documented_support_graph
    if read_fails:
        source.changes_since.side_effect = OSError("offline")
    else:
        source.changes_since.return_value = replace(
            source.changes_since.return_value, current_version=0
        )

    with pytest.raises(KynoUnavailableError if read_fails else ValueError):
        exec(compile(checkpoint_code, "docs/langgraph.md", "exec"), namespace)

    namespace["model"].invoke.assert_not_called()
