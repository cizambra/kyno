import pytest

from kyno.wire.constitution import InvalidConstitutionKeyError, check_constitution_key


@pytest.mark.parametrize(
    "value, expected",
    [
        (None, "default"),
        ("default", "default"),
        ("a", "a"),
        ("0", "0"),
        ("team-2-eu", "team-2-eu"),
        ("  eu-west\n", "eu-west"),
        (" a" + "b" * 199 + " ", "a" + "b" * 199),
    ],
)
def test_given_valid_key_when_check_constitution_key_runs_then_surrounding_whitespace_is_removed(
    value, expected
):
    assert check_constitution_key(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "",
        " \n",
        "Acme",
        "acme/eu",
        "acme--eu",
        "acme_eu",
        "-acme",
        "acme-",
        "équipe",
        "team\nsupport",
        "team\tsupport",
        "team\x00support",
        "１２３",
        "a" * 201,
        1,
        True,
        [],
        {},
        b"support",
    ],
)
def test_given_invalid_key_when_check_constitution_key_runs_then_typed_key_error_is_raised(
    value,
):
    with pytest.raises(InvalidConstitutionKeyError, match="constitution key"):
        check_constitution_key(value)
