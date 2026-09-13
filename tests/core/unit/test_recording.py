from dataclasses import FrozenInstanceError

import pytest

from kyno.recording import RecordingPolicy, RecordingsSettings


def test_given_default_recordings_settings_when_reading_policy_then_it_is_never():
    assert RecordingsSettings().policy is RecordingPolicy.NEVER


def test_given_always_policy_when_building_recordings_settings_then_it_is_preserved():
    assert RecordingsSettings(RecordingPolicy.ALWAYS).policy is RecordingPolicy.ALWAYS


def test_given_recordings_settings_when_mutating_policy_then_it_is_rejected():
    settings = RecordingsSettings()
    with pytest.raises(FrozenInstanceError):
        settings.policy = RecordingPolicy.ALWAYS


@pytest.mark.parametrize("policy", ["never", "always"])
def test_given_string_policy_when_building_recordings_settings_then_it_becomes_an_enum(policy):
    assert RecordingsSettings(policy).policy is RecordingPolicy(policy)


@pytest.mark.parametrize("policy", ["sometimes", "ALWAYS", "", None, True])
def test_given_invalid_policy_when_building_recordings_settings_then_it_is_rejected(policy):
    with pytest.raises(ValueError):
        RecordingsSettings(policy)
