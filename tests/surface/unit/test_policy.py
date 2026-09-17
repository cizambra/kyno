from kyno.sdk.errors import KynoUnavailableError
from kyno.sdk.policy import PullPolicy
from kyno.wire.errors import CoherenceError


def test_given_no_choice_when_building_a_pull_policy_then_the_default_is_fail_open():
    assert PullPolicy().fail_closed is False


def test_given_fail_closed_when_building_a_pull_policy_then_it_preserves_the_choice():
    assert PullPolicy(fail_closed=True).fail_closed is True


def test_given_the_error_types_when_comparing_then_unavailable_is_a_coherence_error():
    assert issubclass(KynoUnavailableError, CoherenceError)
