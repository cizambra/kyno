import threading

import pytest
import uvicorn

from kyno.service import ControlPlane
from kyno.transports import build_http_app
from tests.mcp_requests import mint, token_store
from tests.servers import free_port, wait_until


@pytest.fixture
def server_store():
    store = token_store()
    yield store
    store.engine.dispose()


@pytest.fixture
def live_server(server_store):
    control_plane = ControlPlane(server_store)
    token = mint(server_store, scope="read")
    app = build_http_app(control_plane, token_store=server_store)
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        wait_until(lambda: server.started, "uvicorn did not come up")
        yield control_plane, f"http://127.0.0.1:{port}/mcp", token
    finally:
        server.should_exit = True
        thread.join(timeout=5)
