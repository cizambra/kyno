from contextlib import asynccontextmanager
from typing import NamedTuple

import pytest
from pydantic import AnyUrl

from kyno.errors import KynoUnavailableError
from kyno.mcp_server import RESOURCE_URI, build_server
from kyno.sdk.binder import DirectionBinder
from kyno.sdk.cell import DirectionCell
from kyno.sdk.client import McpDirectionSource, SessionRunner
from kyno.sdk.policy import PULL_FAILED_STALE, RecordingSink
from kyno.sdk.subscriber import BackgroundSubscriber
from kyno.service import ControlPlane
from kyno.store.sql import SqlConstitutionStore


class Wiring(NamedTuple):
    subscriber: BackgroundSubscriber
    bump: object
    cell: DirectionCell
    control_plane: ControlPlane
    runner: SessionRunner


@pytest.fixture
def wiring():
    """A real server, a real subscription, and a subscriber -- all in this
    process over the SDK's in-memory transport.

    `bump` writes through the MCP tool rather than the ControlPlane object:
    the server only emits resources/updated from inside its own event loop,
    which is exactly where a real write arrives.
    """
    built: list[BackgroundSubscriber] = []

    def build(source=None, constitutions=("default", "eu"), telemetry=None, preset=None):
        store = SqlConstitutionStore(url="sqlite://")
        store.create_all()
        control_plane = ControlPlane(store)
        if preset is not None:
            control_plane.set_direction(mission=preset, change_note="init")
        server = build_server(control_plane)

        @asynccontextmanager
        async def connect(message_handler=None):
            from mcp.shared.memory import create_connected_server_and_client_session

            async with create_connected_server_and_client_session(
                server, message_handler=message_handler
            ) as session:
                yield session

        runner = SessionRunner(connect)
        cell = DirectionCell()
        subscriber = BackgroundSubscriber(
            runner,
            source if source is not None else McpDirectionSource(runner),
            cell,
            constitutions=constitutions,
            telemetry=telemetry,
        )
        subscriber.start()
        built.append(subscriber)

        def bump(mission: str, constitution: str = "default") -> None:
            runner.call(
                lambda session: session.call_tool(
                    "set_direction",
                    {"mission": mission, "change_note": mission, "constitution": constitution},
                )
            )

        return Wiring(subscriber, bump, cell, control_plane, runner)

    try:
        yield build
    finally:
        for subscriber in built:
            subscriber.stop()


@pytest.fixture
def wired(wiring):
    built = wiring()
    return built.subscriber, built.bump, built.cell


def test_a_version_bump_reaches_the_cell(wired):
    subscriber, bump, cell = wired

    bump("M1")

    assert subscriber.wait_for_version("default", 1)
    assert cell.get("default").mission == "M1"


def test_a_bump_on_another_constitution_wakes_us_harmlessly(wired):
    # The subscribable resource is the default constitution's, so any bump
    # wakes every subscriber; the re-pull is by name, so a default-bound cell
    # simply learns default is unchanged.
    subscriber, bump, cell = wired

    bump("EU", constitution="eu")

    assert subscriber.wait_for_version("eu", 1)
    assert cell.known_version("default") == 0


def test_the_cell_ends_at_the_latest_version_after_a_burst(wired):
    subscriber, bump, cell = wired
    for i in range(1, 6):
        bump(f"M{i}")

    assert subscriber.wait_for_version("default", 5)
    assert cell.get("default").version == 5 and cell.get("default").mission == "M5"


def test_a_manual_notify_refreshes_without_a_server_bump(wired):
    subscriber, bump, _cell = wired
    bump("M1")
    assert subscriber.wait_for_version("default", 1)

    before = subscriber.refreshes
    subscriber.notify()

    assert subscriber.wait_for_refresh(before + 1)


def test_stop_is_idempotent(wired):
    subscriber, _bump, _cell = wired
    subscriber.stop()
    subscriber.stop()


def test_starting_pulls_once_so_the_cell_is_warm_before_any_push(wiring):
    """A crew that starts mid-flight must not wait for the next bump."""
    built = wiring(preset="Already set")

    assert built.subscriber.wait_for_version("default", 1)
    assert built.cell.get("default").mission == "Already set"


def test_stopping_closes_the_session_it_was_given(wired):
    subscriber, _bump, _cell = wired
    subscriber.stop()

    with pytest.raises(KynoUnavailableError):
        subscriber._runner.call(lambda session: session.list_tools())


def test_a_failed_re_pull_is_reported_and_the_thread_survives(wiring, scripted_source):
    scripted_source.set("default", 2, "M2")
    scripted_source.failure = OSError("connection refused")
    sink = RecordingSink()
    built = wiring(source=scripted_source, constitutions=("default",), telemetry=sink)

    assert built.subscriber.wait_for_refresh(1)
    assert [e.kind for e in sink.events] == [PULL_FAILED_STALE]

    scripted_source.failure = None
    built.subscriber.notify()

    assert built.subscriber.wait_for_version("default", 2)


def test_a_push_and_the_next_pull_share_one_cell(wiring):
    """Pull and push must agree: the push warms what the bind returns."""
    built = wiring()
    binder = DirectionBinder(McpDirectionSource(built.runner), cell=built.cell)

    built.bump("M1")
    assert built.subscriber.wait_for_version("default", 1)

    direction = binder.bind()

    assert direction.version == 1 and direction.mission == "M1"


def test_a_dropped_subscription_still_binds_fresh_on_the_next_pull(wiring):
    """Push is the optimization: with the subscription gone, the next pull
    still binds the current version."""
    built = wiring()
    assert built.subscriber.wait_for_refresh(1)
    binder = DirectionBinder(McpDirectionSource(built.runner), cell=built.cell)
    built.runner.call(lambda session: session.unsubscribe_resource(AnyUrl(RESOURCE_URI)))

    built.bump("M1")
    built.bump("M2")

    assert binder.bind().version == 2


def test_every_named_constitution_is_refreshed_on_one_wake(wired):
    subscriber, bump, cell = wired

    bump("EU", constitution="eu")
    bump("US")

    assert subscriber.wait_for_version("eu", 1)
    assert subscriber.wait_for_version("default", 1)
    assert cell.names() == ("default", "eu")


def test_notification_spam_coalesces_into_one_pending_wake():
    # A wake means "re-pull everything by name", so a second pending one adds
    # nothing; a flood of notifications must never grow memory.
    subscriber = BackgroundSubscriber(runner=None, source=None, cell=DirectionCell())

    for _ in range(1000):
        subscriber.notify()

    assert subscriber._wakes.qsize() == 1


def test_stop_still_shuts_down_with_a_wake_already_pending(wired):
    subscriber, _bump, _cell = wired
    subscriber.notify()

    subscriber.stop()

    assert subscriber._worker is None


def test_a_wake_never_rolls_the_cell_back(wired):
    """The push and the pull race by design; the cell is the tiebreaker."""
    subscriber, bump, cell = wired
    bump("M1")
    bump("M2")
    assert subscriber.wait_for_version("default", 2)

    before = subscriber.refreshes
    subscriber.notify()
    assert subscriber.wait_for_refresh(before + 1)

    assert cell.get("default").version == 2
