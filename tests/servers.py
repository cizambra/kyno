"""Support for tests that run a real HTTP server."""

import socket
import time


def free_port() -> int:
    # Nothing holds the port between this call and the caller's bind, so
    # another process can still take it. Binding port 0 and reading the
    # port back closes that window, but only for a server in this process.
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_until(condition, description, *, timeout=10.0, interval=0.05):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(interval)
    raise AssertionError(f"{description} within {timeout:g}s")
