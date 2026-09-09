from contextlib import asynccontextmanager

import pytest

import kyno
from kyno.config import ProfileError, add_credentials, add_remote
from kyno.sdk import connect


@pytest.fixture
def captured_binding(monkeypatch):
    captured = {}

    class FakeRunner:
        def __init__(self, session_factory):
            captured["session_factory"] = session_factory

        def start(self):
            captured["started"] = True

        def close(self):
            captured["closed"] = True

    def fake_http_session(binding):
        captured["binding"] = binding

        @asynccontextmanager
        async def factory(message_handler=None):
            yield object()

        return factory

    monkeypatch.setattr("kyno.sdk.http_session", fake_http_session)
    monkeypatch.setattr("kyno.sdk.SessionRunner", FakeRunner)
    return captured


def test_given_only_legacy_environment_wiring_when_connecting_then_it_is_refused(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("KYNO_URL", "https://legacy.example.com/mcp")
    monkeypatch.setenv("KYNO_TOKEN", "legacy-token")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(
        "kyno.sdk.http_session",
        lambda binding: pytest.fail("connection started before profile resolution"),
    )

    with pytest.raises(ProfileError, match="no remote profile 'default'"):
        connect()


def test_given_arguments_when_connecting_then_the_binding_is_built_from_them(captured_binding):
    connection = connect(url="http://kyno.internal:8080/mcp/", token="t-1")
    try:
        assert captured_binding["binding"].endpoint == "http://kyno.internal:8080/mcp/"
        assert captured_binding["binding"].token == "t-1"
    finally:
        connection.close()


def test_given_a_default_profile_when_connecting_then_the_profile_is_resolved(
    captured_binding, monkeypatch, tmp_path
):
    monkeypatch.setenv("HOME", str(tmp_path))
    add_credentials(token_env="APP_TOKEN")
    add_remote("http://from-profile:8080", token_env="APP_TOKEN")
    monkeypatch.setenv("APP_TOKEN", "profile-token")
    monkeypatch.setenv("KYNO_URL", "http://ignored:8080/mcp")
    monkeypatch.setenv("KYNO_TOKEN", "ignored-token")
    connection = connect()
    try:
        assert captured_binding["binding"].endpoint == "http://from-profile:8080/mcp"
        assert captured_binding["binding"].token == "profile-token"
    finally:
        connection.close()


def test_given_a_blank_profile_when_connecting_then_it_is_refused(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    add_remote("https://default.example.com", token_env="APP_TOKEN")
    monkeypatch.setenv("APP_TOKEN", "default-token")

    with pytest.raises(ProfileError, match="no remote profile ''"):
        connect(profile="")


def test_given_a_named_profile_and_token_override_when_connecting_then_the_profile_url_is_used(
    captured_binding, monkeypatch, tmp_path
):
    monkeypatch.setenv("HOME", str(tmp_path))
    add_remote("https://ops.example.com/base/", "ops", token_env="APP_TOKEN")
    connection = connect(profile="ops", token="override")
    try:
        assert captured_binding["binding"].endpoint == "https://ops.example.com/base/mcp"
        assert captured_binding["binding"].token == "override"
    finally:
        connection.close()


def test_given_a_default_profile_and_token_override_when_connecting_then_the_override_is_used(
    captured_binding, monkeypatch, tmp_path
):
    monkeypatch.setenv("HOME", str(tmp_path))
    add_remote("https://default.example.com", token_env="APP_TOKEN")
    connection = connect(token="override")
    try:
        assert captured_binding["binding"].endpoint == "https://default.example.com/mcp"
        assert captured_binding["binding"].token == "override"
    finally:
        connection.close()


def test_given_a_profile_when_its_token_rotates_after_connecting_then_the_connection_keeps_identity(
    captured_binding, monkeypatch, tmp_path
):
    monkeypatch.setenv("HOME", str(tmp_path))
    add_remote("https://ops.example.com", "ops", token_env="APP_TOKEN")
    monkeypatch.setenv("APP_TOKEN", "before-rotation")
    connection = connect(profile="ops")
    try:
        monkeypatch.setenv("APP_TOKEN", "after-rotation")
        assert captured_binding["binding"].token == "before-rotation"
    finally:
        connection.close()


@pytest.mark.parametrize("token", [None, "", "   "])
def test_given_an_explicit_url_without_a_token_when_connecting_then_it_is_refused(token):
    with pytest.raises(ProfileError, match="requires token"):
        connect(url="https://kyno.example.com/mcp", token=token)


def test_given_a_profile_with_a_blank_token_override_when_connecting_then_it_is_refused(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("HOME", str(tmp_path))
    add_remote("https://ops.example.com", "ops", token_env="APP_TOKEN")

    with pytest.raises(ProfileError, match="blank token"):
        connect(profile="ops", token="   ")


def test_given_an_invalid_explicit_endpoint_when_connecting_then_it_is_refused(monkeypatch):
    monkeypatch.setattr(
        "kyno.sdk.http_session",
        lambda binding: pytest.fail("connection started before endpoint validation"),
    )

    with pytest.raises(ProfileError, match="ending in /mcp"):
        connect(url="https://kyno.example.com/api", token="t")


def test_given_a_profile_and_explicit_url_when_connecting_then_the_sources_are_refused():
    with pytest.raises(ProfileError, match="profile.*url"):
        connect(profile="ops", url="https://kyno.example.com/mcp", token="t")


def test_given_the_sdk_when_looking_for_the_entry_point_then_it_is_kyno_connect():
    assert kyno.connect is connect
