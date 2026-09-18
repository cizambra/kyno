"""A real CrewAI crew retains completed work across direction changes over authenticated HTTP."""

from pathlib import Path

import pytest
import yaml

from kyno.sdk import PullPolicy, connect
from kyno.sdk.errors import KynoUnavailableError


@pytest.fixture
def fake_llm():
    from crewai import BaseLLM
    from pydantic import Field

    class FakeLLM(BaseLLM):
        calls: list = Field(default_factory=list)
        fail_on: int = 0
        response: str | None = None

        def call(self, messages, **kwargs):
            self.calls.append([message.copy() for message in messages])
            if len(self.calls) == self.fail_on:
                raise RuntimeError("model failed")
            return self.response or f"Final Answer: Completed step {len(self.calls)}"

    return FakeLLM(model="fake")


@pytest.mark.parametrize("changed", [True, False])
def test_given_a_completed_draft_when_direction_is_checked_then_remaining_work_uses_the_plan(
    crewai_example, fake_llm, live_server, changed
):
    control_plane, url, token = live_server
    directory = Path(crewai_example.__file__).parent
    initial = yaml.safe_load((directory / "direction-v1.yaml").read_text())
    revised = yaml.safe_load((directory / "direction-v2.yaml").read_text())
    control_plane.set_direction(**initial, change_note="initial")
    events = []

    def operator():
        assert len(fake_llm.calls) == 2
        if changed:
            control_plane.set_direction(**revised, change_note="new tradeoff")

    with connect(url=url, token=token) as connection:
        state = crewai_example.run_example(
            fake_llm,
            connection.binder("customer-support", policy=PullPolicy(fail_closed=True)),
            model_name="fake",
            wait_for_operator=operator,
            emit=lambda event: (events.append(event), crewai_example.report(event)),
        )

    receipts = [event for event in events if event["event"] == "direction_supplied"]
    assert [event["version"] for event in receipts] == ([1, 1, 2, 2] if changed else [1, 1, 1])
    assert [event["step_id"] for event in receipts] == (
        ["plan", "first_answer", "replan", "second_answer"]
        if changed
        else ["plan", "first_answer", "second_answer"]
    )
    assert "Completed step 1" in receipts[1]["task"]
    assert initial["mission"] in receipts[0]["direction"]
    if changed:
        assert revised["mission"] in receipts[-1]["direction"]
        assert "new tradeoff" in receipts[2]["task"]
    assert "Completed step 2" in receipts[-1]["task"]
    assert state["first_answer"] == "Completed step 2"
    assert state["plan_version"] == (2 if changed else 1)
    assert f"Completed step {3 if changed else 1}" in receipts[-1]["task"]
    for receipt, messages in zip(receipts, fake_llm.calls, strict=True):
        assert any(message["content"] == receipt["direction"] for message in messages)
    assert [event["call_id"] for event in events[::2]] == [
        event["call_id"] for event in events[1::2]
    ]
    assert token not in str(events)
    assert [event["response"]["content"] for event in events[1::2]] == [
        f"Final Answer: Completed step {index + 1}" for index in range(len(fake_llm.calls))
    ]


@pytest.mark.parametrize("failed_call", [1, 2, 3, 4])
def test_given_model_failure_when_a_stage_runs_then_no_output_or_retry_is_recorded(
    crewai_example, fake_llm, live_server, failed_call
):
    control_plane, url, token = live_server
    control_plane.set_direction(mission="Help", change_note="initial")
    fake_llm.fail_on = failed_call
    events = []
    with (
        connect(url=url, token=token) as connection,
        pytest.raises(RuntimeError, match="model failed"),
    ):
        crewai_example.run_example(
            fake_llm,
            connection.binder(),
            model_name="fake",
            wait_for_operator=lambda: control_plane.set_direction(
                mission="Choice", change_note="new"
            ),
            emit=events.append,
        )
    assert len(fake_llm.calls) == failed_call
    assert [event["event"] for event in events] == (
        ["direction_supplied", "model_output"] * (failed_call - 1) + ["direction_supplied"]
    )


@pytest.mark.parametrize("failure", ["unwritten", "recording", "pull"])
def test_given_unavailable_direction_or_recording_when_starting_then_inference_is_blocked(
    crewai_example, fake_llm, live_server, monkeypatch, failure
):
    control_plane, url, token = live_server
    if failure != "unwritten":
        control_plane.set_direction(mission="Help", change_note="initial")

    def fail(*args, **kwargs):
        raise OSError("unavailable")

    if failure == "pull":
        monkeypatch.setattr(control_plane, "changes_since", fail)
    expected = {"unwritten": ValueError, "recording": OSError, "pull": KynoUnavailableError}[
        failure
    ]
    with connect(url=url, token=token) as connection, pytest.raises(expected):
        crewai_example.run_example(
            fake_llm,
            connection.binder(policy=PullPolicy(fail_closed=True)),
            model_name="fake",
            wait_for_operator=lambda: None,
            emit=fail if failure == "recording" else lambda event: None,
        )
    assert fake_llm.calls == []


@pytest.mark.parametrize("failed_read", [2, 3, 4, 5])
@pytest.mark.parametrize("fail_closed", [False, True])
def test_given_a_failed_pull_when_the_cycle_continues_then_no_later_inference_runs(
    crewai_example, fake_llm, live_server, monkeypatch, failed_read, fail_closed
):
    control_plane, url, token = live_server
    control_plane.set_direction(mission="Help", change_note="initial")
    original = control_plane.changes_since
    reads = []

    def read(*args, **kwargs):
        reads.append(args)
        if len(reads) == failed_read:
            raise OSError("offline")
        return original(*args, **kwargs)

    monkeypatch.setattr(control_plane, "changes_since", read)
    expected = KynoUnavailableError if fail_closed else ValueError
    with connect(url=url, token=token) as connection, pytest.raises(expected):
        crewai_example.run_example(
            fake_llm,
            connection.binder(policy=PullPolicy(fail_closed=fail_closed)),
            model_name="fake",
            emit=lambda event: None,
            wait_for_operator=lambda: control_plane.set_direction(
                mission="Choice", change_note="new"
            ),
        )
    assert len(fake_llm.calls) == {2: 1, 3: 2, 4: 2, 5: 3}[failed_read]
    assert len(reads) == failed_read


def test_given_operator_cancellation_when_paused_then_the_completed_draft_is_the_last_call(
    crewai_example, fake_llm, live_server
):
    control_plane, url, token = live_server
    control_plane.set_direction(mission="Help", change_note="initial")

    def cancel():
        raise EOFError("closed")

    with connect(url=url, token=token) as connection, pytest.raises(EOFError):
        crewai_example.run_example(
            fake_llm,
            connection.binder(),
            model_name="fake",
            emit=lambda event: None,
            wait_for_operator=cancel,
        )
    assert len(fake_llm.calls) == 2


def test_given_plain_output_when_crewai_finishes_each_stage_then_it_uses_one_call_per_stage(
    crewai_example, fake_llm, live_server
):
    control_plane, url, token = live_server
    control_plane.set_direction(mission="Help", change_note="initial")
    fake_llm.response = "Thought: I should think again"
    events = []
    with connect(url=url, token=token) as connection:
        crewai_example.run_example(
            fake_llm,
            connection.binder(),
            model_name="fake",
            emit=events.append,
            wait_for_operator=lambda: None,
        )
    assert len(fake_llm.calls) == 3
    assert [event["event"] for event in events] == ["direction_supplied", "model_output"] * 3


def test_given_output_recording_failure_when_a_call_completes_then_later_stages_do_not_run(
    crewai_example, fake_llm, live_server
):
    control_plane, url, token = live_server
    control_plane.set_direction(mission="Help", change_note="initial")

    def emit(event):
        if event["event"] == "model_output":
            raise OSError("disk full")

    with connect(url=url, token=token) as connection, pytest.raises(OSError, match="disk full"):
        crewai_example.run_example(
            fake_llm,
            connection.binder(),
            model_name="fake",
            emit=emit,
            wait_for_operator=lambda: None,
        )
    assert len(fake_llm.calls) == 1


def test_given_a_framework_retry_when_the_call_budget_is_used_then_inference_is_blocked(
    crewai_example, fake_llm, live_server, monkeypatch
):
    import crewai

    original_agent = crewai.Agent

    def retrying_agent(**kwargs):
        return original_agent(**{**kwargs, "max_iter": 2})

    monkeypatch.setattr(crewai, "Agent", retrying_agent)
    control_plane, url, token = live_server
    control_plane.set_direction(mission="Help", change_note="initial")
    fake_llm.response = "Thought: Use a tool\nAction: unavailable\nAction Input: {}"
    events = []
    with connect(url=url, token=token) as connection, pytest.raises(RuntimeError, match="budget"):
        crewai_example.run_example(
            fake_llm,
            connection.binder(),
            model_name="fake",
            emit=events.append,
            wait_for_operator=lambda: None,
        )
    assert len(fake_llm.calls) == 1
    assert [event["event"] for event in events] == ["direction_supplied", "model_output"]
