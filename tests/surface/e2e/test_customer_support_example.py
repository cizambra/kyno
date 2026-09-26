"""The customer-support graph reads direction over HTTP and records each model call separately."""

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from kyno.sdk import DetailLevel, PullPolicy, connect
from kyno.sdk.errors import KynoUnavailableError
from tests.mcp_requests import mint


@pytest.fixture
def model():
    from langchain_core.messages import AIMessage

    class Model:
        def __init__(self):
            self.calls = []

        def invoke(self, messages):
            self.calls.append(messages)
            return AIMessage(content="Deterministic test output", id="test-output")

    return Model()


@pytest.mark.e2e
def test_given_operator_update_when_run_example_resumes_graph_then_each_call_records_its_direction(
    example, live_server, server_store, tmp_path, monkeypatch
):
    from langchain_core.messages import AIMessage

    control_plane, url, token = live_server
    directory = Path(example.__file__).parent
    initial = yaml.safe_load((directory / "direction-v1.yaml").read_text())
    revised = yaml.safe_load((directory / "direction-v2.yaml").read_text())
    initial_key = initial.pop("constitution")
    control_plane.apply_direction(constitution_key=initial_key, **initial, change_note="initial")
    operator_token = mint(server_store, scope="write", name="operator")
    reads = []
    original_read = control_plane.changes_since

    def read(*args, **kwargs):
        reads.append(args)
        return original_read(*args, **kwargs)

    monkeypatch.setattr(control_plane, "changes_since", read)
    events, calls = [], []
    responses = [
        AIMessage(content=content, id=f"fake-{index}", response_metadata={"test": True})
        for index, content in enumerate(
            ["Initial response plan", "Completed draft", "Revised finalization plan", "Final reply"]
        )
    ]

    class Model:
        def invoke(self, messages):
            assert events[-1]["event"] == "direction_supplied"
            assert events[-1]["direction"] == messages[0]["content"]
            calls.append(messages)
            return responses[len(calls) - 1]

    def operator():
        assert len(calls) == 2
        environment = {
            "HOME": str(tmp_path),
            "PYTHONPATH": str(directory.parents[1] / "src"),
            "OPERATOR_TOKEN": operator_token,
        }
        for arguments in (
            ["remote", "add", "--url", url, "--token-env", "OPERATOR_TOKEN"],
            [
                "apply",
                str(directory / "direction-v2.yaml"),
                "--remote",
                "--no-interactive",
                "--note",
                "review tradeoffs",
            ],
        ):
            result = subprocess.run(
                [sys.executable, "-c", "from kyno.cli import app; app()", *arguments],
                cwd=tmp_path,
                env=environment,
                capture_output=True,
                text=True,
                timeout=30,
            )
            assert result.returncode == 0, result.stderr

    def record_and_print(event):
        events.append(event)
        example.report(event)

    with connect(url=url, token=token) as connection:
        state = example.run_example(
            Model(),
            connection.binder(
                "customer-support", detail=DetailLevel.FULL, policy=PullPolicy(fail_closed=True)
            ),
            model_name="deterministic-test",
            wait_for_operator=operator,
            emit=record_and_print,
        )

    receipts = [event for event in events if event["event"] == "direction_supplied"]
    outputs = [event for event in events if event["event"] == "model_output"]
    assert len(reads) == 5
    assert [event["version"] for event in receipts] == [1, 1, 2, 2]
    assert all(event["status"] == "pulled" for event in receipts)
    assert len({event["run_id"] for event in events}) == 1
    assert [event["step_id"] for event in receipts] == [
        "plan",
        "first_answer",
        "replan",
        "second_answer",
    ]
    assert len({event["call_id"] for event in receipts}) == 4
    assert [event["call_id"] for event in outputs] == [event["call_id"] for event in receipts]
    assert [event["response"] for event in outputs] == [
        response.model_dump(mode="json") for response in responses
    ]
    assert all(example.SCENARIO in call[1]["content"] for call in calls)
    assert "review tradeoffs" in receipts[2]["task"]
    assert "Initial response plan" in calls[1][1]["content"]
    assert "Completed draft" in calls[2][1]["content"]
    assert "Initial response plan" in calls[2][1]["content"]
    assert "Revised finalization plan" in calls[3][1]["content"]
    assert "Completed draft" in calls[3][1]["content"]
    assert state["plan_version"] == 2
    assert state["first_answer"] == "Completed draft"
    assert state["second_answer"] == "Final reply"
    assert revised["mission"] in calls[2][0]["content"]
    assert initial["mission"] in receipts[0]["direction"]
    assert all(token not in str(event) for event in events)
    assert all(operator_token not in str(event) for event in events)


@pytest.mark.e2e
def test_given_unchanged_direction_when_graph_resumes_then_it_skips_replanning(
    example, live_server, model
):
    control_plane, url, token = live_server
    control_plane.apply_direction(mission="Help", change_note="initial")
    events = []
    with connect(url=url, token=token) as connection:
        example.run_example(
            model,
            connection.binder("default"),
            model_name="fake",
            wait_for_operator=lambda: None,
            emit=events.append,
        )
    assert [event["version"] for event in events if event["event"] == "direction_supplied"] == [
        1,
        1,
        1,
    ]
    assert len(model.calls) == 3
    assert [event["step_id"] for event in events if event["event"] == "direction_supplied"] == [
        "plan",
        "first_answer",
        "second_answer",
    ]


@pytest.mark.e2e
@pytest.mark.parametrize("failed_call", [1, 2, 3, 4], ids=["plan", "draft", "replan", "final"])
def test_given_model_failure_when_graph_calls_model_then_failed_call_has_direction_but_no_output(
    example, live_server, model, failed_call
):
    control_plane, url, token = live_server
    control_plane.apply_direction(mission="Help", change_note="initial")
    events = []

    class FailedModel:
        def invoke(self, messages):
            if len(model.calls) + 1 == failed_call:
                raise RuntimeError("model failed")
            return model.invoke(messages)

    def operator():
        assert failed_call > 2
        control_plane.apply_direction(mission="Revised", change_note="update")

    with (
        connect(url=url, token=token) as connection,
        pytest.raises(RuntimeError, match="model failed"),
    ):
        example.run_example(
            FailedModel(),
            connection.binder("default"),
            model_name="fake",
            wait_for_operator=operator,
            emit=events.append,
        )
    assert [event["event"] for event in events] == (
        ["direction_supplied", "model_output"] * (failed_call - 1) + ["direction_supplied"]
    )
    assert len(model.calls) == failed_call - 1


@pytest.mark.e2e
def test_given_an_unwritten_constitution_when_starting_then_no_model_call_or_receipt_is_created(
    example, live_server, model
):
    _, url, token = live_server
    events = []
    with (
        connect(url=url, token=token) as connection,
        pytest.raises(ValueError, match="written constitution"),
    ):
        example.run_example(
            model,
            connection.binder("missing"),
            model_name="fake",
            wait_for_operator=lambda: None,
            emit=events.append,
        )
    assert model.calls == []
    assert events == []


@pytest.mark.e2e
@pytest.mark.parametrize("fail_closed", [False, True])
def test_given_failed_change_check_when_graph_resumes_then_no_replan_or_final_model_call_occurs(
    example, live_server, model, monkeypatch, fail_closed
):
    control_plane, url, token = live_server
    control_plane.apply_direction(mission="Help", change_note="initial")
    events = []

    def fail(*args, **kwargs):
        raise OSError("unavailable")

    def operator():
        monkeypatch.setattr(control_plane, "changes_since", fail)

    expected = KynoUnavailableError if fail_closed else ValueError
    with connect(url=url, token=token) as connection, pytest.raises(expected):
        example.run_example(
            model,
            connection.binder("default", policy=PullPolicy(fail_closed=fail_closed)),
            model_name="fake",
            wait_for_operator=operator,
            emit=events.append,
        )
    assert len(model.calls) == 2
    assert [event["event"] for event in events] == ["direction_supplied", "model_output"] * 2


@pytest.mark.e2e
@pytest.mark.parametrize("failed_read", [1, 2, 4, 5], ids=["plan", "draft", "replan", "final"])
def test_given_failed_pull_when_graph_enters_model_node_then_that_model_call_does_not_run(
    example, live_server, model, monkeypatch, failed_read
):
    control_plane, url, token = live_server
    control_plane.apply_direction(mission="Help", change_note="initial")
    original_read = control_plane.changes_since
    reads = []
    events = []

    def read(*args, **kwargs):
        reads.append(args)
        if len(reads) == failed_read:
            raise OSError("unavailable")
        return original_read(*args, **kwargs)

    def operator():
        control_plane.apply_direction(mission="Revised", change_note="update")

    monkeypatch.setattr(control_plane, "changes_since", read)
    with connect(url=url, token=token) as connection, pytest.raises(KynoUnavailableError):
        example.run_example(
            model,
            connection.binder(policy=PullPolicy(fail_closed=True)),
            model_name="fake",
            wait_for_operator=operator,
            emit=events.append,
        )

    completed_calls = {1: 0, 2: 1, 4: 2, 5: 3}[failed_read]
    assert len(model.calls) == completed_calls
    assert len(reads) == failed_read
    assert [event["event"] for event in events] == (
        ["direction_supplied", "model_output"] * completed_calls
    )


@pytest.mark.e2e
@pytest.mark.parametrize("failure", ["write", "flush"])
def test_given_failed_receipt_storage_when_starting_then_the_model_is_not_called(
    example, live_server, model, failure
):
    control_plane, url, token = live_server
    control_plane.apply_direction(mission="Help", change_note="initial")

    class Recording:
        def write(self, text):
            if failure == "write":
                raise OSError("recording unavailable")

        def flush(self):
            if failure == "flush":
                raise OSError("recording unavailable")

    recording = Recording()
    with (
        connect(url=url, token=token) as connection,
        pytest.raises(OSError, match="recording unavailable"),
    ):
        example.run_example(
            model,
            connection.binder("default"),
            model_name="fake",
            wait_for_operator=lambda: None,
            emit=lambda event: example.report(event, recording),
        )
    assert model.calls == []


@pytest.mark.e2e
def test_given_operator_cancellation_when_paused_then_only_plan_and_first_answer_are_recorded(
    example, live_server, model
):
    control_plane, url, token = live_server
    control_plane.apply_direction(mission="Help", change_note="initial")
    events = []

    def cancel():
        raise EOFError("operator terminal closed")

    with connect(url=url, token=token) as connection, pytest.raises(EOFError):
        example.run_example(
            model,
            connection.binder("default"),
            model_name="fake",
            wait_for_operator=cancel,
            emit=events.append,
        )
    assert len(model.calls) == 2
    assert [event["event"] for event in events] == ["direction_supplied", "model_output"] * 2
