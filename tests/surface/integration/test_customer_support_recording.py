"""Customer-support command consent and optional recording through its application seams."""

import json
import sys
from types import SimpleNamespace

import pytest

from kyno.sdk import DetailLevel


def test_given_no_model_consent_when_starting_then_no_connection_is_opened(example, monkeypatch):
    def unexpected_connect(**kwargs):
        pytest.fail("No connection without explicit consent")

    monkeypatch.setattr(example.kyno, "connect", unexpected_connect)
    with pytest.raises(SystemExit) as error:
        example.main(["--url", "http://localhost:9000", "--model", "operator-selected"])
    assert error.value.code == 2


@pytest.mark.parametrize("record", [False, True])
@pytest.mark.parametrize("failure", [False, True])
@pytest.mark.parametrize("token_env", ["KYNO_READ_TOKEN", "SUPPORT_READ_TOKEN"])
def test_given_explicit_consent_when_running_then_recording_is_opt_in_and_connections_close(
    example, monkeypatch, tmp_path, record, failure, token_env, capsys
):
    events = [
        {
            "event": "direction_supplied",
            "run_id": "run",
            "step_id": "first_answer",
            "constitution": "support",
            "version": 1,
            "status": "current",
        },
        {"event": "model_output", "response": {"content": "Unmodified output"}},
    ]
    opened = []

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            opened.append("closed")

        def binder(self, **kwargs):
            assert kwargs["context"] is DetailLevel.FULL
            assert kwargs["policy"].fail_closed
            return "binder"

    def connect_to_server(**kwargs):
        assert kwargs == {"url": "http://localhost:9000", "token": "read-secret"}
        return Connection()

    def create_model(**kwargs):
        assert kwargs == {"model": "operator-selected", "max_retries": 0, "timeout": 60}
        return "model"

    def run(model, binder, **kwargs):
        assert (model, binder) == ("model", "binder")
        for event in events:
            kwargs["emit"](event)
            if failure:
                raise RuntimeError("model-secret")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("KYNO_READ_TOKEN", "unused-default")
    monkeypatch.setenv(token_env, "read-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "model-secret")
    monkeypatch.setitem(sys.modules, "langchain_openai", SimpleNamespace(ChatOpenAI=create_model))
    monkeypatch.setattr(example.kyno, "connect", connect_to_server)
    monkeypatch.setattr(example, "run_example", run)
    options = ["--record", str(tmp_path / "receipts.jsonl")] if record else []
    assert example.main(
        [
            "--url",
            "http://localhost:9000",
            "--model",
            "operator-selected",
            "--allow-model-calls",
            "--token-env",
            token_env,
            *options,
        ]
    ) == (1 if failure else 0)
    assert opened == ["closed"]
    if record:
        assert [
            json.loads(line) for line in (tmp_path / "receipts.jsonl").read_text().splitlines()
        ] == (events[:1] if failure else events)
    else:
        assert list(tmp_path.iterdir()) == []
    output = capsys.readouterr()
    assert "read-secret" not in output.out + output.err
    assert "model-secret" not in output.out + output.err


@pytest.mark.parametrize("missing", ["KYNO_READ_TOKEN", "OPENAI_API_KEY", "model"])
def test_given_missing_model_configuration_when_starting_then_no_connection_is_opened(
    example, monkeypatch, missing
):
    monkeypatch.setenv("KYNO_READ_TOKEN", "read-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "model-secret")
    if missing != "model":
        monkeypatch.delenv(missing)

    def unexpected_connect(**kwargs):
        pytest.fail("Configuration must be validated before connecting")

    monkeypatch.setattr(example.kyno, "connect", unexpected_connect)
    with pytest.raises(SystemExit) as error:
        example.main(
            [
                "--url",
                "http://localhost:9000",
                "--model",
                " " if missing == "model" else "selected",
                "--allow-model-calls",
            ]
        )
    assert error.value.code == 2


def test_given_an_existing_recording_when_starting_then_it_is_preserved_without_model_calls(
    example, tmp_path, monkeypatch
):
    path = tmp_path / "recording.jsonl"
    path.write_text("original")
    monkeypatch.setenv("KYNO_READ_TOKEN", "read-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "model-secret")

    def unexpected_model(**kwargs):
        pytest.fail("Existing recordings must be refused before constructing a model")

    monkeypatch.setitem(
        sys.modules, "langchain_openai", SimpleNamespace(ChatOpenAI=unexpected_model)
    )
    assert (
        example.main(
            [
                "--url",
                "http://localhost:9000",
                "--model",
                "test",
                "--allow-model-calls",
                "--record",
                str(path),
            ]
        )
        == 1
    )
    assert path.read_text() == "original"
