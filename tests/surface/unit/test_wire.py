from kyno.wire.errors import CoherenceError, MalformedPrincipleError
from kyno.wire.models import COMPACT, DIRECTION_MARKER, FULL, Principle, check_detail


def test_given_a_wire_detail_when_checking_it_then_the_same_value_is_returned():
    assert check_detail(COMPACT) == COMPACT
    assert check_detail(FULL) == FULL


def test_given_a_wire_principle_when_serializing_compact_then_only_the_title_is_returned():
    assert Principle("safe", "Keep the boundary explicit").to_dict(COMPACT) == {"title": "safe"}


def test_given_a_malformed_wire_principle_when_constructing_it_then_a_wire_error_is_raised():
    try:
        Principle.of({"description": "missing title"})
    except MalformedPrincipleError as error:
        assert isinstance(error, CoherenceError)
    else:
        raise AssertionError("expected MalformedPrincipleError")


def test_given_the_wire_marker_when_reading_it_then_it_is_the_shared_marker():
    assert DIRECTION_MARKER == "[kyno:direction"
