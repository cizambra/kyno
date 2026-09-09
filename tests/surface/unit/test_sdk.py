from contextlib import asynccontextmanager

import pytest

import kyno
from kyno.config import ProfileError, add_credentials, add_remote
from kyno.sdk import connect


def test_given_wiring_without_an_endpoint_when_connecting_then_it_is_refused(monkeypatch, tmp_path):
    monkeypatch.delenv("KYNO_URL", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    with pytest.raises(ProfileError):
        connect()


def test_given_arguments_when_connecting_then_the_binding_is_built_from_them(monkeypatch):
    captured = {}

    def fake_http_session(binding):
        captured["binding"] = binding

        @asynccontextmanager
        async def factory(message_handler=None):
            yield object()

        return factory

    monkeypatch.setattr("kyno.sdk.http_session", fake_http_session)
    connection = connect(url="http://kyno.internal:8080/mcp/", token="t-1")
    try:
        assert captured["binding"].endpoint == "http://kyno.internal:8080/mcp/"
        assert captured["binding"].token == "t-1"
    finally:
        connection.close()


def test_given_a_default_profile_when_connecting_then_the_profile_is_resolved(
    monkeypatch, tmp_path
):
    captured = {}

    def fake_http_session(binding):
        captured["binding"] = binding

        @asynccontextmanager
        async def factory(message_handler=None):
            yield object()

        return factory

    monkeypatch.setattr("kyno.sdk.http_session", fake_http_session)
    monkeypatch.setenv("HOME", str(tmp_path))
    add_credentials(token_env="APP_TOKEN")
    add_remote("http://from-profile:8080", token_env="APP_TOKEN")
    monkeypatch.setenv("APP_TOKEN", "profile-token")
    monkeypatch.setenv("KYNO_URL", "http://ignored:8080/mcp")
    monkeypatch.setenv("KYNO_TOKEN", "ignored-token")
    connection = connect()
    try:
        assert captured["binding"].endpoint == "http://from-profile:8080/mcp"
        assert captured["binding"].token == "profile-token"
    finally:
        connection.close()


def test_given_a_named_profile_and_token_override_when_connecting_then_the_profile_url_is_used(
    monkeypatch, tmp_path
):
    captured = {}

    def fake_http_session(binding):
        captured["binding"] = binding

        @asynccontextmanager
        async def factory(message_handler=None):
            yield object()

        return factory

    monkeypatch.setattr("kyno.sdk.http_session", fake_http_session)
    monkeypatch.setenv("HOME", str(tmp_path))
    add_remote("https://ops.example.com/base/", "ops", token_env="APP_TOKEN")
    connection = connect(profile="ops", token="override")
    try:
        assert captured["binding"].endpoint == "https://ops.example.com/base/mcp"
        assert captured["binding"].token == "override"
    finally:
        connection.close()


def test_given_a_profile_when_its_token_rotates_after_connecting_then_the_connection_keeps_identity(
    monkeypatch, tmp_path
):
    captured = {}

    def fake_http_session(binding):
        captured["binding"] = binding

        @asynccontextmanager
        async def factory(message_handler=None):
            yield object()

        return factory

    monkeypatch.setattr("kyno.sdk.http_session", fake_http_session)
    monkeypatch.setenv("HOME", str(tmp_path))
    add_remote("https://ops.example.com", "ops", token_env="APP_TOKEN")
    monkeypatch.setenv("APP_TOKEN", "before-rotation")
    connection = connect(profile="ops")
    try:
        monkeypatch.setenv("APP_TOKEN", "after-rotation")
        assert captured["binding"].token == "before-rotation"
    finally:
        connection.close()


def test_given_an_explicit_url_without_a_token_when_connecting_then_it_is_refused():
    with pytest.raises(ProfileError, match="requires token"):
        connect(url="https://kyno.example.com/mcp")


def test_given_a_profile_and_explicit_url_when_connecting_then_the_sources_are_refused():
    with pytest.raises(ProfileError, match="profile.*url"):
        connect(profile="ops", url="https://kyno.example.com/mcp", token="t")


def test_given_the_sdk_when_looking_for_the_entry_point_then_it_is_kyno_connect():
    assert kyno.connect is connect
