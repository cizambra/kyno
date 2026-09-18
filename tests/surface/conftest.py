import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def example(monkeypatch):
    pytest.importorskip("langgraph")
    path = Path(__file__).resolve().parents[2] / "examples/customer_support/run.py"
    monkeypatch.syspath_prepend(str(path.parent))
    spec = importlib.util.spec_from_file_location("support_example", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def crewai_example(monkeypatch):
    monkeypatch.setenv("CREWAI_TELEMETRY_DISABLED", "true")
    monkeypatch.setenv("CREWAI_TRACING_ENABLED", "false")
    pytest.importorskip("crewai")
    from crewai.hooks import get_after_llm_call_hooks, get_before_llm_call_hooks

    before_hooks = get_before_llm_call_hooks()
    after_hooks = get_after_llm_call_hooks()
    directory = Path(__file__).resolve().parents[2] / "examples/customer_support"
    monkeypatch.syspath_prepend(str(directory))
    spec = importlib.util.spec_from_file_location("crewai_example", directory / "crewai_run.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    yield module
    assert get_before_llm_call_hooks() == before_hooks
    assert get_after_llm_call_hooks() == after_hooks
