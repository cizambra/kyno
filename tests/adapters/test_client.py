import pytest

from kyno.adapters.core.client import DirectionSource, KynoBinding, LocalDirectionSource


def test_binding_defaults_to_the_default_constitution():
    binding = KynoBinding()
    assert binding.constitution == "default"
    assert binding.endpoint is None and binding.token is None


def test_binding_from_env_reads_url_and_token(monkeypatch):
    monkeypatch.setenv("KYNO_URL", "https://kyno.internal/mcp")
    monkeypatch.setenv("KYNO_TOKEN", "secret")
    binding = KynoBinding.from_env(constitution="eu")
    assert binding.endpoint == "https://kyno.internal/mcp"
    assert binding.token == "secret" and binding.constitution == "eu"


def test_binding_from_env_without_token_is_none_not_empty(monkeypatch):
    monkeypatch.delenv("KYNO_URL", raising=False)
    monkeypatch.setenv("KYNO_TOKEN", "")
    assert KynoBinding.from_env().token is None


def test_local_source_serves_the_named_constitution(control_plane):
    control_plane.set_direction(mission="EU mission", change_note="init", constitution="eu")
    control_plane.set_direction(mission="US mission", change_note="init", constitution="us")
    source = LocalDirectionSource(control_plane)

    assert source.changes_since(0, "eu").mission == "EU mission"
    assert source.changes_since(0, "us").mission == "US mission"


def test_local_source_reads_an_unwritten_name_as_version_zero(control_plane):
    changes = LocalDirectionSource(control_plane).changes_since(0, "never-written")
    assert changes.current_version == 0 and changes.changed is False


def test_local_source_satisfies_the_protocol(control_plane):
    assert isinstance(LocalDirectionSource(control_plane), DirectionSource)


def test_local_source_propagates_a_future_known_version(control_plane):
    from kyno.errors import UnknownVersionError

    control_plane.set_direction(mission="M", change_note="init")
    with pytest.raises(UnknownVersionError):
        LocalDirectionSource(control_plane).changes_since(99, "default")


def test_binding_from_env_treats_an_empty_url_as_unset(monkeypatch):
    monkeypatch.setenv("KYNO_URL", "")
    assert KynoBinding.from_env().endpoint is None


def test_a_binding_cannot_be_repointed_after_construction():
    binding = KynoBinding(constitution="eu")
    with pytest.raises(Exception):  # noqa: B017 - frozen dataclass raises FrozenInstanceError
        binding.constitution = "us"


def test_the_repr_of_a_binding_never_contains_the_token():
    # Bindings travel into logs and tracebacks; the credential must not.
    binding = KynoBinding(constitution="eu", endpoint="https://kyno.internal/mcp", token="hunter2")
    assert "hunter2" not in repr(binding)
    assert "eu" in repr(binding)


def test_two_bindings_with_the_same_wiring_are_equal_and_hashable():
    wiring = {"constitution": "eu", "endpoint": "https://kyno.internal/mcp", "token": "t"}
    assert KynoBinding(**wiring) == KynoBinding(**wiring)
    assert len({KynoBinding(**wiring), KynoBinding(**wiring)}) == 1


def test_one_source_serves_two_bindings_without_crosstalk(control_plane):
    """The use case: one process runs an EU crew and a US crew off one plane."""
    control_plane.set_direction(mission="EU v1", change_note="init", constitution="eu")
    control_plane.set_direction(mission="US v1", change_note="init", constitution="us")
    source = LocalDirectionSource(control_plane)
    eu, us = KynoBinding(constitution="eu"), KynoBinding(constitution="us")

    control_plane.set_direction(mission="EU v2", change_note="pivot", constitution="eu")

    after_eu = source.changes_since(1, eu.constitution)
    after_us = source.changes_since(1, us.constitution)
    assert after_eu.changed is True and after_eu.mission == "EU v2"
    assert after_us.changed is False and after_us.mission == "US v1"


def test_local_source_reports_every_note_since_the_known_version(control_plane):
    control_plane.set_direction(mission="M", change_note="init")
    control_plane.set_direction(principles=("P",), change_note="add P")
    control_plane.set_direction(mission="M2", change_note="repoint")

    changes = LocalDirectionSource(control_plane).changes_since(1, "default")
    assert changes.current_version == 3
    assert changes.change_notes == ("add P", "repoint")
    assert changes.changed_mission is True and changes.changed_principles is True
