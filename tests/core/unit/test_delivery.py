from dataclasses import FrozenInstanceError

import pytest

from kyno.delivery import DeliverySettings, RecordingPolicy


def test_given_default_delivery_settings_when_reading_policy_then_it_is_never():
    assert DeliverySettings().recording_policy is RecordingPolicy.NEVER


def test_given_always_policy_when_building_delivery_settings_then_it_is_preserved():
    assert DeliverySettings(RecordingPolicy.ALWAYS).recording_policy is RecordingPolicy.ALWAYS


def test_given_delivery_settings_when_mutating_policy_then_it_is_rejected():
    settings = DeliverySettings()
    with pytest.raises(FrozenInstanceError):
        settings.recording_policy = RecordingPolicy.ALWAYS


@pytest.mark.parametrize("policy", ["never", "always"])
def test_given_string_policy_when_building_delivery_settings_then_it_becomes_an_enum(policy):
    assert DeliverySettings(policy).recording_policy is RecordingPolicy(policy)


@pytest.mark.parametrize("policy", ["sometimes", "ALWAYS", "", None, True])
def test_given_invalid_policy_when_building_delivery_settings_then_it_is_rejected(policy):
    with pytest.raises(ValueError):
        DeliverySettings(policy)


def test_given_default_delivery_settings_when_reading_recording_timeout_then_it_is_one_second():
    assert DeliverySettings().recording_timeout_seconds == 1.0


@pytest.mark.parametrize("timeout", [0.01, 1, 2.5])
def test_given_positive_timeout_when_building_delivery_settings_then_seconds_are_preserved(timeout):
    assert DeliverySettings(recording_timeout_seconds=timeout).recording_timeout_seconds == timeout


@pytest.mark.parametrize(
    "timeout", [0, -1, float("nan"), float("inf"), -float("inf"), True, "1", None]
)
def test_given_invalid_timeout_when_building_delivery_settings_then_it_is_rejected(timeout):
    with pytest.raises(
        ValueError, match="recording_timeout_seconds must be a positive finite number"
    ):
        DeliverySettings(recording_timeout_seconds=timeout)
