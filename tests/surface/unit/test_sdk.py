from contextlib import asynccontextmanager

import pytest

import kyno
from kyno.errors import KynoUnavailableError
from kyno.sdk import connect


def test_given_wiring_without_an_endpoint_when_connecting_then_it_is_refused(monkeypatch):
    monkeypatch.delenv("KYNO_URL", raising=False)
    with pytest.raises(KynoUnavailableError):
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
    connection = connect("http://kyno.internal:8080/mcp/", token="t-1")
    try:
        assert captured["binding"].endpoint == "http://kyno.internal:8080/mcp/"
        assert captured["binding"].token == "t-1"
    finally:
        connection.close()


def test_given_no_arguments_when_connecting_then_the_environment_is_the_fallback(monkeypatch):
    captured = {}

    def fake_http_session(binding):
        captured["binding"] = binding

        @asynccontextmanager
        async def factory(message_handler=None):
            yield object()

        return factory

    monkeypatch.setattr("kyno.sdk.http_session", fake_http_session)
    monkeypatch.setenv("KYNO_URL", "http://from-env:8080/mcp/")
    monkeypatch.setenv("KYNO_TOKEN", "env-token")
    connection = connect()
    try:
        assert captured["binding"].endpoint == "http://from-env:8080/mcp/"
        assert captured["binding"].token == "env-token"
    finally:
        connection.close()


def test_given_the_sdk_when_looking_for_the_entry_point_then_it_is_kyno_connect():
    assert kyno.connect is connect
