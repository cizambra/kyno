import pytest

from kyno.wire.constitution import (
    InvalidConstitutionKeyError,
    check_constitution_key,
    is_constitution_key,
    suggest_constitution_key,
)


@pytest.mark.parametrize("key", ["a", "0", "support", "team-2-eu"])
def test_given_lowercase_key_when_is_constitution_key_runs_then_true_is_returned(key):
    assert is_constitution_key(key) is True


@pytest.mark.parametrize("key", ["", " support ", "support\n", "Acme", "a--b", "a/b"])
def test_given_invalid_format_when_is_constitution_key_runs_then_false_is_returned(key):
    assert is_constitution_key(key) is False


@pytest.mark.parametrize("key", ["équipe", "support-٢", "support-２"])
def test_given_non_ascii_letters_or_digits_when_checking_key_format_then_it_is_rejected(key):
    assert is_constitution_key(key) is False


def test_given_a_key_longer_than_200_characters_when_checking_format_then_it_is_accepted():
    assert is_constitution_key("a" * 201) is True


@pytest.mark.parametrize("text, expected", [("Acme EU", "acme-eu"), ("///", "")])
def test_given_display_text_when_suggest_constitution_key_runs_then_suggestion_is_returned(
    text, expected
):
    assert suggest_constitution_key(text) == expected


@pytest.mark.parametrize(
    "key",
    [
        None,
        "",
        " ",
        " support ",
        "support\n",
        "Acme",
        "a/b",
        "a--b",
        "a_b",
        "-a",
        "a-",
        "é",
        1,
        True,
        [],
    ],
)
def test_given_invalid_key_when_check_constitution_key_runs_then_typed_key_error_is_raised(key):
    with pytest.raises(InvalidConstitutionKeyError, match="constitution key"):
        check_constitution_key(key)


@pytest.mark.parametrize("key", ["a", "0", "team-2-eu", "a" * 201])
def test_given_valid_key_when_check_constitution_key_runs_then_spelling_is_preserved(key):
    assert check_constitution_key(key) == key


@pytest.mark.parametrize(
    "key, expected",
    [
        (
            "Acme EU",
            "'Acme EU' is not a valid constitution key: use lowercase letters and digits "
            "with single hyphens like 'acme-eu'",
        ),
        (
            "///",
            "'///' is not a valid constitution key: use lowercase letters and digits "
            "with single hyphens",
        ),
    ],
)
def test_given_invalid_key_when_validating_then_error_has_format_and_available_suggestion(
    key, expected
):
    with pytest.raises(InvalidConstitutionKeyError) as refusal:
        check_constitution_key(key)
    assert str(refusal.value) == expected
