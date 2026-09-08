import pytest

from kyno.config import ProfileError, add_credentials, add_remote, normalize_endpoint, resolve


def test_given_a_profile_when_resolving_from_the_mit_config_package_then_the_token_is_returned(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("HOME", str(tmp_path))
    add_credentials(token_env="KYNO_TOKEN")
    add_remote("https://kyno.example.com", token_env="KYNO_TOKEN")
    monkeypatch.setenv("KYNO_TOKEN", "secret")

    resolved = resolve()

    assert resolved.url == "https://kyno.example.com"
    assert resolved.token == "secret"


def test_given_a_missing_profile_when_resolving_from_the_mit_config_package_then_it_names_the_fix(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("HOME", str(tmp_path))

    try:
        resolve()
    except ProfileError as error:
        assert "kyno remote add --url URL" in str(error)
    else:
        raise AssertionError("expected ProfileError")


def test_given_a_profile_base_url_when_normalizing_then_exactly_one_mcp_suffix_is_added():
    assert normalize_endpoint("https://kyno.example.com/base/mcp///", profile=True) == (
        "https://kyno.example.com/base/mcp"
    )


def test_given_an_explicit_url_without_the_mcp_endpoint_when_normalizing_then_it_is_refused():
    with pytest.raises(ProfileError, match="full MCP endpoint"):
        normalize_endpoint("https://kyno.example.com/base", profile=False)
