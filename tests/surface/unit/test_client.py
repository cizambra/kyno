import asyncio
import json

import pytest

from kyno.sdk.client import KynoBinding, McpDirectionSource
from kyno.wire.models import DetailLevel


def test_given_no_name_when_building_a_binding_then_the_default_constitution_is_used():
    binding = KynoBinding()
    assert binding.endpoint is None
    assert binding.endpoint is None and binding.token is None


def test_given_a_built_binding_when_repointing_then_it_is_refused():
    binding = KynoBinding()
    with pytest.raises(Exception):  # noqa: B017 - frozen dataclass raises FrozenInstanceError
        binding.endpoint = "https://elsewhere/mcp"


def test_given_a_binding_when_reading_its_repr_then_the_token_is_never_there():
    # Bindings travel into logs and tracebacks; the credential must not.
    binding = KynoBinding(endpoint="https://kyno.internal/mcp", token="hunter2")
    assert "hunter2" not in repr(binding)
    assert "kyno.internal" in repr(binding)


def test_given_two_bindings_with_one_wiring_when_comparing_then_they_are_equal_and_hashable():
    wiring = {"endpoint": "https://kyno.internal/mcp", "token": "t"}
    assert KynoBinding(**wiring) == KynoBinding(**wiring)
    assert len({KynoBinding(**wiring), KynoBinding(**wiring)}) == 1


def test_given_a_typed_detail_when_pulling_over_mcp_then_the_argument_is_a_plain_string():
    seen = {}

    class Session:
        async def call_tool(self, name, arguments):
            seen.update(arguments)
            payload = {
                "current_version": 0,
                "changed": False,
                "mission": "",
                "principles": [],
                "changed_mission": False,
                "changed_principles": False,
                "change_notes": [],
            }
            text = type("Text", (), {"text": json.dumps(payload)})()
            return type("Reply", (), {"content": [text]})()

    class Runner:
        def call(self, operation):
            return asyncio.run(operation(Session()))

    McpDirectionSource(Runner()).changes_since(0, "default", DetailLevel.FULL)

    assert seen["detail"] == "full"
    assert type(seen["detail"]) is str


def test_given_an_unknown_detail_when_pulling_over_mcp_then_it_is_refused_before_the_call():
    class Runner:
        def call(self, operation):
            raise AssertionError("MCP must not be called")

    with pytest.raises(ValueError, match="verbose"):
        McpDirectionSource(Runner()).changes_since(0, "default", "verbose")
