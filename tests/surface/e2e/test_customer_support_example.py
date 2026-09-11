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
def test_given_an_operator_update_when_the_graph_continues_then_each_call_records_its_direction(
    example, live_server, server_store, tmp_path, monkeypatch
):
    from langchain_core.messages import AIMessage

    control_plane, url, token = live_server
    directory = Path(example.__file__).parent
    initial = yaml.safe_load((directory / "direction-v1.yaml").read_text())
    revised = yaml.safe_load((directory / "direction-v2.yaml").read_text())
    control_plane.set_direction(**initial, change_note="initial")
    operator_token = mint(server_store, scope="write", name="operator")
    reads = []
    original_read = control_plane.changes_since

    def read(*args, **kwargs):
        reads.append(args)
        return original_read(*args, **kwargs)

    monkeypatch.setattr(control_plane, "changes_since", read)
    events, calls = [], []
    response = AIMessage(
        content="Recorded test response", id="fake-message", response_metadata={"test": True}
    )

    class Model:
        def invoke(self, messages):
            assert events[-1]["event"] == "direction_supplied"
            assert events[-1]["direction"] == messages[0]["content"]
            calls.append(messages)
            return response

    def operator():
        assert len(calls) == 1
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
        example.run_example(
            Model(),
            connection.binder(context=DetailLevel.FULL, policy=PullPolicy(fail_closed=True)),
            constitution="customer-support",
            model_name="deterministic-test",
            wait_for_operator=operator,
            emit=record_and_print,
        )

    receipts = [event for event in events if event["event"] == "direction_supplied"]
    outputs = [event for event in events if event["event"] == "model_output"]
    assert len(reads) == 2
    assert [event["version"] for event in receipts] == [1, 2]
    assert [event["status"] for event in receipts] == ["current", "current"]
    assert len({event["run_id"] for event in events}) == 1
    assert [event["step_id"] for event in receipts] == ["first_answer", "second_answer"]
    assert len({event["call_id"] for event in receipts}) == 2
    assert [event["call_id"] for event in outputs] == [event["call_id"] for event in receipts]
    assert all(event["response"] == response.model_dump(mode="json") for event in outputs)
    assert calls[0][1:] == calls[1][1:]
    assert "review tradeoffs" in receipts[1]["direction"]
    assert revised["mission"] in calls[1][0]["content"]
    assert initial["mission"] in receipts[0]["direction"]
    assert all(token not in str(event) for event in events)
    assert all(operator_token not in str(event) for event in events)


@pytest.mark.e2e
def test_given_no_operator_change_when_the_graph_continues_then_both_receipts_name_the_same_version(
    example, live_server, model
):
    control_plane, url, token = live_server
    control_plane.set_direction(mission="Help", change_note="initial")
    events = []
    with connect(url=url, token=token) as connection:
        example.run_example(
            model,
            connection.binder(),
            constitution="default",
            model_name="fake",
            wait_for_operator=lambda: None,
            emit=events.append,
        )
    assert [event["version"] for event in events if event["event"] == "direction_supplied"] == [
        1,
        1,
    ]
    assert len(model.calls) == 2


@pytest.mark.e2e
def test_given_a_model_failure_when_answering_then_only_the_supplied_direction_is_recorded(
    example, live_server
):
    control_plane, url, token = live_server
    control_plane.set_direction(mission="Help", change_note="initial")
    events = []

    class FailedModel:
        def invoke(self, messages):
            raise RuntimeError("model failed")

    def unexpected_pause():
        pytest.fail("The graph must stop before the operator pause")

    with (
        connect(url=url, token=token) as connection,
        pytest.raises(RuntimeError, match="model failed"),
    ):
        example.run_example(
            FailedModel(),
            connection.binder(),
            constitution="default",
            model_name="fake",
            wait_for_operator=unexpected_pause,
            emit=events.append,
        )
    assert [event["event"] for event in events] == ["direction_supplied"]


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
            connection.binder(),
            constitution="missing",
            model_name="fake",
            wait_for_operator=lambda: None,
            emit=events.append,
        )
    assert model.calls == []
    assert events == []


@pytest.mark.e2e
@pytest.mark.parametrize("fail_closed", [False, True])
def test_given_a_failed_second_pull_when_the_graph_continues_then_no_second_model_call_occurs(
    example, live_server, model, monkeypatch, fail_closed
):
    control_plane, url, token = live_server
    control_plane.set_direction(mission="Help", change_note="initial")
    events = []

    def fail(*args, **kwargs):
        raise OSError("unavailable")

    def operator():
        monkeypatch.setattr(control_plane, "changes_since", fail)

    expected = KynoUnavailableError if fail_closed else ValueError
    with connect(url=url, token=token) as connection, pytest.raises(expected):
        example.run_example(
            model,
            connection.binder(policy=PullPolicy(fail_closed=fail_closed)),
            constitution="default",
            model_name="fake",
            wait_for_operator=operator,
            emit=events.append,
        )
    assert len(model.calls) == 1
    assert [event["event"] for event in events] == ["direction_supplied", "model_output"]
