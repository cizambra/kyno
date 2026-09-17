"""CrewAI's observed receipt links application output to the served version over HTTP."""

from types import SimpleNamespace

import pytest

pytest.importorskip("crewai")

from crewai.hooks import LLMCallHookContext  # noqa: E402

from kyno.adapters.crewai import CrewAiKyno  # noqa: E402
from kyno.delivery import RecordingPolicy  # noqa: E402
from kyno.delivery_recording import DeliveryRecorder  # noqa: E402
from kyno.sdk import connect  # noqa: E402
from kyno.store.delivery_record import SqlDeliveryRecordStore  # noqa: E402


@pytest.mark.e2e
def test_given_new_direction_when_before_llm_call_runs_again_then_prior_record_keeps_old_version(
    live_server, server_store
):
    control_plane, url, token = live_server
    history = SqlDeliveryRecordStore(server_store.engine)
    control_plane.delivery_recorder = DeliveryRecorder(history, RecordingPolicy.ALWAYS)
    control_plane.set_direction(mission="Resolve delivery complaints", change_note="initial")
    executor = SimpleNamespace(
        messages=[], llm=None, iterations=0, agent=None, task=None, crew=None
    )
    context = LLMCallHookContext(executor=executor)
    observed = []

    with connect(url=url, token=token) as connection:
        adapter = CrewAiKyno(
            connection.binder(correlation_id="support-run", metadata={"agent": "support"}),
            on_direction=observed.append,
        )
        adapter.before_llm_call(context)
        answer_record = {
            "record_id": observed[0].recording.record_id,
            "supplied_message": context.messages[0]["content"],
            "output": "We will review the delayed delivery.",
        }
        control_plane.set_direction(mission="Route billing disputes", change_note="new priority")
        adapter.before_llm_call(context)

    record = history.get(answer_record["record_id"])
    version = server_store.get(record["requested_constitution"], record["served_version"])

    assert record["served_version"] == observed[0].direction.version == 1
    assert version.mission == "Resolve delivery complaints"
    assert record["correlation_id"] == "support-run"
    assert record["metadata"] == {"agent": "support"}
    assert answer_record["output"] == "We will review the delayed delivery."
    assert version.mission in answer_record["supplied_message"]
    assert "output" not in record
    assert observed[1].recording.record_id != answer_record["record_id"]
    assert history.get(observed[1].recording.record_id)["served_version"] == 2
