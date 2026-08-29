import pytest

from kyno.sdk.client import DirectionSource, KynoBinding, LocalDirectionSource


def test_given_no_name_when_building_a_binding_then_the_default_constitution_is_used():
    binding = KynoBinding()
    assert binding.endpoint is None
    assert binding.endpoint is None and binding.token is None


def test_given_env_wiring_when_building_a_binding_then_the_url_and_token_are_read(monkeypatch):
    monkeypatch.setenv("KYNO_URL", "https://kyno.internal/mcp")
    monkeypatch.setenv("KYNO_TOKEN", "secret")
    binding = KynoBinding.from_env()
    assert binding.endpoint == "https://kyno.internal/mcp"
    assert binding.token == "secret"


def test_given_env_without_a_token_when_building_a_binding_then_the_token_is_none_not_empty(
    monkeypatch,
):
    monkeypatch.delenv("KYNO_URL", raising=False)
    monkeypatch.setenv("KYNO_TOKEN", "")
    assert KynoBinding.from_env().token is None


def test_given_a_local_source_when_pulling_a_name_then_that_constitution_serves(control_plane):
    control_plane.set_direction(mission="EU mission", change_note="init", constitution="eu")
    control_plane.set_direction(mission="US mission", change_note="init", constitution="us")
    source = LocalDirectionSource(control_plane)

    assert source.changes_since(0, "eu").mission == "EU mission"
    assert source.changes_since(0, "us").mission == "US mission"


def test_given_an_unwritten_name_when_a_local_source_reads_then_it_is_version_zero(control_plane):
    changes = LocalDirectionSource(control_plane).changes_since(0, "never-written")
    assert changes.current_version == 0 and changes.changed is False


def test_given_the_local_source_when_checking_the_protocol_then_it_satisfies_it(control_plane):
    assert isinstance(LocalDirectionSource(control_plane), DirectionSource)


def test_given_a_future_known_version_when_a_local_source_pulls_then_the_error_propagates(
    control_plane,
):
    from kyno.errors import UnknownVersionError

    control_plane.set_direction(mission="M", change_note="init")
    with pytest.raises(UnknownVersionError):
        LocalDirectionSource(control_plane).changes_since(99, "default")


def test_given_an_empty_url_in_env_when_building_a_binding_then_it_reads_as_unset(monkeypatch):
    monkeypatch.setenv("KYNO_URL", "")
    assert KynoBinding.from_env().endpoint is None


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


def test_given_one_source_when_serving_two_bindings_then_there_is_no_crosstalk(control_plane):
    """The use case: one process runs an EU crew and a US crew off one plane."""
    control_plane.set_direction(mission="EU v1", change_note="init", constitution="eu")
    control_plane.set_direction(mission="US v1", change_note="init", constitution="us")
    source = LocalDirectionSource(control_plane)
    eu, us = "eu", "us"

    control_plane.set_direction(mission="EU v2", change_note="pivot", constitution="eu")

    after_eu = source.changes_since(1, eu)
    after_us = source.changes_since(1, us)
    assert after_eu.changed is True and after_eu.mission == "EU v2"
    assert after_us.changed is False and after_us.mission == "US v1"


def test_given_a_known_version_when_a_local_source_reports_then_every_note_since_comes(
    control_plane,
):
    control_plane.set_direction(mission="M", change_note="init")
    control_plane.set_direction(principles=("P",), change_note="add P")
    control_plane.set_direction(mission="M2", change_note="repoint")

    changes = LocalDirectionSource(control_plane).changes_since(1, "default")
    assert changes.current_version == 3
    assert changes.change_notes == ("add P", "repoint")
    assert changes.changed_mission is True and changes.changed_principles is True
