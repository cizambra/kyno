"""The one rule for config values: written in, or one ${VAR} reference."""

import pytest

from kyno.envref import resolve
from kyno.errors import ConfigError
from kyno.profiles import ProfileError


def test_given_a_literal_value_when_resolving_then_it_passes_through_stripped():
    assert resolve("  db.internal  ", owner="database.host") == "db.internal"


def test_given_a_reference_when_the_variable_is_set_then_its_value_answers(monkeypatch):
    monkeypatch.setenv("ACME_HOST", "db.internal")
    assert resolve("${ACME_HOST}", owner="database.host") == "db.internal"


def test_given_an_unset_reference_when_resolving_then_owner_and_variable_are_named():
    with pytest.raises(ConfigError, match=r"database.host reads \$\{ACME_GONE\}, which is not set"):
        resolve("${ACME_GONE}", owner="database.host")


def test_given_a_blank_reference_when_resolving_then_it_is_refused_not_empty(monkeypatch):
    monkeypatch.setenv("ACME_BLANK", "   ")
    with pytest.raises(ConfigError, match="which is set but blank"):
        resolve("${ACME_BLANK}", owner="database.password")


def test_given_a_caller_with_its_own_error_type_when_refusing_then_that_type_raises():
    with pytest.raises(ProfileError, match="which is not set"):
        resolve("${ACME_GONE}", owner="credentials 'ci'", error=ProfileError)


def test_given_text_that_only_contains_a_reference_shape_when_resolving_then_it_stays_literal():
    # A reference is the WHOLE value; "${X} and more" is just text.
    assert resolve("prefix-${ACME}-suffix", owner="k") == "prefix-${ACME}-suffix"
