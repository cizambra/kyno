import pytest

from kyno.wire.constitution import check_constitution_key


@pytest.mark.parametrize(
    "value, expected",
    [
        ("default", "default"),
        ("  eu-west\n", "eu-west"),
        (" a" + "b" * 199 + " ", "a" + "b" * 199),
    ],
)
def test_given_valid_key_when_checking_constitution_key_then_normalized_key_returns(
    value, expected
):
    assert check_constitution_key(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        " \n",
        "Acme",
        "acme/eu",
        "acme--eu",
        "acme_eu",
        "-acme",
        "acme-",
        "équipe",
        "a" * 201,
        1,
        True,
        [],
    ],
)
def test_given_invalid_key_when_checking_constitution_key_then_value_is_refused(value):
    with pytest.raises(ValueError, match="constitution key"):
        check_constitution_key(value)
