"""CrewAI command consent protects external resources and preserves opt-in recordings."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("missing", ["consent", "KYNO_READ_TOKEN", "OPENAI_API_KEY", "model"])
def test_given_missing_consent_or_configuration_when_starting_then_no_connection_opens(
    crewai_example, monkeypatch, missing
):
    monkeypatch.setenv("KYNO_READ_TOKEN", "read-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "provider-secret")
    if missing in ("KYNO_READ_TOKEN", "OPENAI_API_KEY"):
        monkeypatch.delenv(missing)

    def unexpected(**kwargs):
        pytest.fail("Must validate before opening external resources")

    monkeypatch.setattr(crewai_example.kyno, "connect", unexpected)
    with pytest.raises(SystemExit) as error:
        crewai_example.main(
            [
                "--url",
                "http://localhost:9000",
                "--model",
                " " if missing == "model" else "selected",
                *([] if missing == "consent" else ["--allow-model-calls"]),
            ]
        )
    assert error.value.code == 2


@pytest.mark.parametrize("record", [True, False])
@pytest.mark.parametrize("failure", [True, False])
def test_given_consent_when_running_then_recording_is_opt_in_and_connections_close(
    crewai_example, monkeypatch, tmp_path, record, failure
):
    import crewai

    closed = []
    event = {"event": "model_output", "response": {"content": "Actual test response"}}

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            closed.append(True)

        def binder(self, constitution, **kwargs):
            assert constitution == "customer-support"
            assert kwargs["policy"].fail_closed
            return "binder"

    def connect(**kwargs):
        assert kwargs == {"url": "http://localhost:9000", "token": "read-secret"}
        return Connection()

    def model(**kwargs):
        assert kwargs == {"model": "selected", "max_retries": 0, "timeout": 60}
        return "model"

    def run(model, binder, **kwargs):
        assert (model, binder) == ("model", "binder")
        kwargs["emit"](event)
        if failure:
            raise RuntimeError("failed")

    monkeypatch.setenv("SUPPORT_TOKEN", "read-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "provider-secret")
    monkeypatch.setattr(crewai, "LLM", model)
    monkeypatch.setattr(crewai_example.kyno, "connect", connect)
    monkeypatch.setattr(crewai_example, "run_example", run)
    path = tmp_path / "recording.jsonl"
    assert crewai_example.main(
        [
            "--url",
            "http://localhost:9000",
            "--model",
            "selected",
            "--allow-model-calls",
            "--token-env",
            "SUPPORT_TOKEN",
            *(["--record", str(path)] if record else []),
        ]
    ) == (1 if failure else 0)
    assert closed == [True]
    if record:
        assert json.loads(path.read_text()) == event
    else:
        assert not path.exists()


def test_given_an_existing_recording_when_starting_then_no_model_is_created(
    crewai_example, monkeypatch, tmp_path
):
    import crewai

    def unexpected(**kwargs):
        pytest.fail("Must preserve recording before constructing a model")

    monkeypatch.setattr(crewai, "LLM", unexpected)
    monkeypatch.setenv("KYNO_READ_TOKEN", "read-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "provider-secret")
    path = tmp_path / "recording.jsonl"
    path.write_text("original")
    assert (
        crewai_example.main(
            [
                "--url",
                "http://localhost:9000",
                "--model",
                "selected",
                "--allow-model-calls",
                "--record",
                str(path),
            ]
        )
        == 1
    )
    assert path.read_text() == "original"


def test_given_an_unrelated_agent_when_hooks_run_then_direction_and_recording_are_untouched(
    crewai_example,
):
    from crewai.hooks import LLMCallHookContext

    class Binder:
        def bind_with_status(self):
            pytest.fail("Must not pull for another agent")

    events = []
    boundary = crewai_example.StageBoundary(Binder(), object(), "prompt", {}, events.append)
    context = LLMCallHookContext(messages=[], agent=object(), response="other output")
    assert boundary.before_call(context) is None
    assert boundary.after_call(context) is None
    assert context.messages == []
    assert events == []


def test_given_a_local_dotenv_when_crewai_is_imported_by_the_example_then_it_is_not_loaded(
    crewai_example, tmp_path
):
    (tmp_path / ".env").write_text("KYNO_EXAMPLE_DOTENV_SENTINEL=unexpected\n")
    directory = str(Path(crewai_example.__file__).parent)
    script = (
        "import os, sys\n"
        f"sys.path.insert(0, {directory!r})\n"
        "import crewai_run\n"
        "import crewai\n"
        "assert 'KYNO_EXAMPLE_DOTENV_SENTINEL' not in os.environ\n"
    )
    environment = dict(os.environ)
    environment.pop("PYTHON_DOTENV_DISABLED", None)
    environment.pop("KYNO_EXAMPLE_DOTENV_SENTINEL", None)
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
