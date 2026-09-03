"""The token value, its hash, and the two small formats around them."""

from datetime import UTC, datetime, timedelta

import pytest

from kyno.tokens import age, generate_value, hash_value, parse_ttl


def test_given_a_minted_value_when_inspecting_it_then_it_carries_the_kyno_prefix():
    value = generate_value()
    assert value.startswith("kyno_")
    # Enough randomness after the prefix to be worth stealing protection.
    assert len(value) > len("kyno_") + 30


def test_given_two_minted_values_when_comparing_then_they_differ():
    assert generate_value() != generate_value()


def test_given_a_value_when_hashing_then_the_hash_is_stable_and_hides_the_value():
    value = "kyno_abc"
    assert hash_value(value) == hash_value(value)
    assert value not in hash_value(value)
    assert len(hash_value(value)) == 64


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("30s", timedelta(seconds=30)),
        ("45m", timedelta(minutes=45)),
        ("2h", timedelta(hours=2)),
        ("7d", timedelta(days=7)),
    ],
)
def test_given_a_number_and_a_unit_when_parsing_a_ttl_then_it_is_the_matching_timedelta(
    text, expected
):
    assert parse_ttl(text) == expected


@pytest.mark.parametrize("text", ["", "2", "h", "2w", "-2h", "0h", "2.5h", "2 h"])
def test_given_a_ttl_that_is_not_a_number_and_a_unit_when_parsing_then_it_refuses_naming_it(text):
    with pytest.raises(ValueError, match=repr(text)):
        parse_ttl(text)


def test_given_no_last_use_when_describing_age_then_it_reads_never():
    assert age(None, datetime.now(UTC)) == "never"


@pytest.mark.parametrize(
    ("delta", "expected"),
    [
        (timedelta(seconds=5), "just now"),
        (timedelta(minutes=2), "2m ago"),
        (timedelta(hours=3), "3h ago"),
        (timedelta(days=9), "9d ago"),
    ],
)
def test_given_a_past_moment_when_describing_age_then_it_reads_in_the_largest_unit_that_fits(
    delta, expected
):
    now = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)
    assert age(now - delta, now) == expected
