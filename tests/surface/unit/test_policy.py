from kyno.sdk.errors import KynoUnavailableError
from kyno.sdk.policy import GatePolicy, PullPolicy
from kyno.wire.errors import CoherenceError


def test_given_no_choice_when_building_the_policy_then_the_default_is_fail_open():
    assert GatePolicy().fail_closed is False
    assert PullPolicy().fail_closed is False
    assert GatePolicy(fail_closed=True).fail_closed is True


def test_given_the_error_types_when_comparing_then_unavailable_is_a_coherence_error():
    assert issubclass(KynoUnavailableError, CoherenceError)
