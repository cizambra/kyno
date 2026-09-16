"""A LangGraph answer retains its served version through recorded HTTP delivery history."""

import pytest

pytest.importorskip("langgraph")

from langgraph.graph import END, START, StateGraph  # noqa: E402

from kyno.adapters.langgraph import KynoState, pull_before  # noqa: E402
from kyno.delivery import RecordingPolicy  # noqa: E402
from kyno.delivery_recording import DeliveryRecorder  # noqa: E402
from kyno.sdk import connect  # noqa: E402
from kyno.store.delivery_record import SqlDeliveryRecordStore  # noqa: E402


@pytest.mark.e2e
def test_given_a_saved_answer_when_core_changes_then_its_record_resolves_the_served_version(
    live_server, server_store
):
    class AnswerState(KynoState, total=False):
        answer_record: dict

    control_plane, url, token = live_server
    history = SqlDeliveryRecordStore(server_store.engine)
    control_plane.delivery_recorder = DeliveryRecorder(history, RecordingPolicy.ALWAYS)
    control_plane.set_direction(mission="Resolve delivery complaints", change_note="initial")

    with connect(url=url, token=token) as connection:
        binder = connection.binder(correlation_id="support-run", metadata={"step": "answer"})

        @pull_before(binder)
        def answer(state):
            return {
                "answer_record": {
                    "record_id": state["kyno_recording"]["record_id"],
                    "supplied_message": state["kyno_direction"],
                    "output": "We will review the delayed delivery.",
                }
            }

        graph = (
            StateGraph(AnswerState)
            .add_node("answer", answer)
            .add_edge(START, "answer")
            .add_edge("answer", END)
            .compile()
        )
        original = graph.invoke({})["answer_record"]
        control_plane.set_direction(mission="Route billing disputes", change_note="new priority")
        newer = graph.invoke({})["answer_record"]

    record = history.get(original["record_id"])
    version = server_store.get(record["requested_constitution"], record["served_version"])

    assert record["served_version"] == 1
    assert version.mission == "Resolve delivery complaints"
    assert record["correlation_id"] == "support-run"
    assert record["metadata"] == {"step": "answer"}
    assert original["output"] == "We will review the delayed delivery."
    assert version.mission in original["supplied_message"]
    assert "output" not in record
    assert newer["record_id"] != original["record_id"]
    assert history.get(newer["record_id"])["served_version"] == 2
