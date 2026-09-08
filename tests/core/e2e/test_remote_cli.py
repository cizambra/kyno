"""Remote CLI journeys against a real HTTP server."""

import pytest

from kyno.cli import app
from kyno.remote import RemoteError
from kyno.service import ControlPlane
from kyno.store.sql import SqlConstitutionStore
from tests.remote_cli import plain, runner, write_file
from tests.servers import free_port, wait_until


@pytest.fixture(autouse=True)
def home(remote_cli_home):
    return remote_cli_home


@pytest.mark.e2e
def test_given_a_live_server_when_applying_remotely_then_the_version_is_applied(
    tmp_path, monkeypatch
):
    """The one true end-to-end: a real HTTP server, the real bearer gate,
    the real client. Everything else in this file skips the wire."""
    import threading

    import uvicorn

    from kyno.tokens import generate_value, hash_value
    from kyno.transports import build_http_app

    store = SqlConstitutionStore(url=f"sqlite:///{tmp_path / 'server.sqlite3'}")
    store.create_all()
    value = generate_value()
    store.add_token("e2e", "write", token_hash=hash_value(value))
    http_app = build_http_app(ControlPlane(store), token_store=store)
    port = free_port()
    server = uvicorn.Server(
        uvicorn.Config(http_app, host="127.0.0.1", port=port, log_level="error")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        wait_until(lambda: server.started, "uvicorn did not come up")
        monkeypatch.setenv("MY_TOKEN", value)
        assert runner.invoke(app, ["credentials", "add", "--token-env", "MY_TOKEN"]).exit_code == 0
        assert (
            runner.invoke(app, ["remote", "add", "--url", f"http://127.0.0.1:{port}"]).exit_code
            == 0
        )
        path = write_file(tmp_path, mission="Live over the wire")
        r = runner.invoke(app, ["set", path, "--note", "e2e", "--remote", "--no-interactive"])
        assert r.exit_code == 0, r.output
        assert store.head("default").mission == "Live over the wire"
        r = runner.invoke(app, ["log", "--remote"])
        assert r.exit_code == 0 and "e2e" in r.stdout
    finally:
        server.should_exit = True
        thread.join(timeout=5)


@pytest.mark.e2e
def test_given_a_revoked_token_when_going_remote_then_the_error_names_the_profile_url_and_401(
    tmp_path, monkeypatch
):
    # The 401 arrives while the session opens, before any tool call.
    import threading

    import uvicorn

    from kyno.tokens import generate_value, hash_value
    from kyno.transports import build_http_app

    store = SqlConstitutionStore(url=f"sqlite:///{tmp_path / 'server.sqlite3'}")
    store.create_all()
    value = generate_value()
    token = store.add_token("e2e", "write", token_hash=hash_value(value))
    http_app = build_http_app(ControlPlane(store), token_store=store)
    port = free_port()
    server = uvicorn.Server(
        uvicorn.Config(http_app, host="127.0.0.1", port=port, log_level="error")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        wait_until(lambda: server.started, "uvicorn did not come up")
        monkeypatch.setenv("MY_TOKEN", value)
        assert runner.invoke(app, ["credentials", "add", "--token-env", "MY_TOKEN"]).exit_code == 0
        assert (
            runner.invoke(app, ["remote", "add", "--url", f"http://127.0.0.1:{port}"]).exit_code
            == 0
        )
        store.revoke_token(token.id)

        r = runner.invoke(app, ["log", "--remote"])

        assert r.exit_code == 1
        assert f"'default' at http://127.0.0.1:{port} refused the token: 401 unauthorized" in (
            plain(r.output)
        )
        assert "TaskGroup" not in r.output
    finally:
        server.should_exit = True
        thread.join(timeout=5)


@pytest.mark.e2e
def test_given_an_endpoint_nothing_listens_on_when_opening_then_cannot_reach_names_the_profile():
    from kyno.profiles import Resolved
    from kyno.remote import RemoteClient

    client = RemoteClient(Resolved(profile="p", url="http://127.0.0.1:9", token="t", chain="c"))
    with pytest.raises(RemoteError, match="cannot reach 'p' at http://127.0.0.1:9"):
        client.open()
