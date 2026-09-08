import pytest

from kyno.sdk.client import KynoBinding


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
