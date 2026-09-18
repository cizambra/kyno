import pytest

from kyno.wire.constitution import is_constitution_key, suggest_constitution_key


@pytest.mark.parametrize("key", ["a", "0", "support", "team-2-eu"])
def test_given_lowercase_key_when_is_constitution_key_runs_then_true_is_returned(key):
    assert is_constitution_key(key) is True


@pytest.mark.parametrize("key", ["", " support ", "support\n", "Acme", "a--b", "a/b"])
def test_given_invalid_format_when_is_constitution_key_runs_then_false_is_returned(key):
    assert is_constitution_key(key) is False


@pytest.mark.parametrize("text, expected", [("Acme EU", "acme-eu"), ("///", "")])
def test_given_display_text_when_suggest_constitution_key_runs_then_suggestion_is_returned(
    text, expected
):
    assert suggest_constitution_key(text) == expected
