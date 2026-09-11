import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def example():
    pytest.importorskip("langgraph")
    path = Path(__file__).resolve().parents[2] / "examples/customer_support/run.py"
    spec = importlib.util.spec_from_file_location("support_example", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
