"""Coercions that name their key."""

import pytest

from kyno.coerce import to_bool, to_int
from kyno.errors import ConfigError


def test_given_an_integer_when_coercing_then_it_comes_back_as_int():
    assert to_int("2256", owner="server.port") == 2256


def test_given_a_non_integer_when_coercing_then_the_owner_is_named():
    with pytest.raises(ConfigError, match="server.port must be an integer, got 'abc'"):
        to_int("abc", owner="server.port")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("true", True),
        ("TRUE", True),
        ("1", True),
        ("yes", True),
        ("on", True),
        ("false", False),
        ("0", False),
        ("no", False),
        ("off", False),
    ],
)
def test_given_configparsers_truth_words_when_coercing_then_they_all_answer(value, expected):
    assert to_bool(value, owner="server.allow_insecure") is expected


def test_given_a_word_outside_the_truth_table_when_coercing_then_the_owner_is_named():
    with pytest.raises(ConfigError, match="server.allow_insecure must be true or false"):
        to_bool("maybe", owner="server.allow_insecure")
