"""What moved between the version a consumer holds and the one in force.

A change note says why the direction changed, in whoever's words wrote it.
The delta says what actually moved, computed. They are separate because a
subtle change -- one principle of four, mission untouched -- arrives as a
block that reads almost identically to the last one, and a note saying "the
direction has changed" points at nothing.
"""

import pytest

from kyno.service import ControlPlane
from kyno.store.sql import SqlConstitutionStore


@pytest.fixture
def plane():
    store = SqlConstitutionStore(url="sqlite://")
    store.create_all()
    plane = ControlPlane(store)
    plane.set_direction(
        mission="Run the agency",
        principles=("Craft first", "Client success over billable hours", "Honest scoping"),
        change_note="initial direction",
    )
    return plane


def test_a_changed_principle_is_named_with_both_wordings(plane):
    plane.set_direction(
        principles=("Craft first", "Retainer outcomes come first", "Honest scoping"),
        change_note="board decision",
    )
    delta = plane.changes_since(1).delta

    assert len(delta) == 1
    assert "Client success over billable hours" in delta[0]
    assert "Retainer outcomes come first" in delta[0]


def test_a_changed_mission_is_named(plane):
    plane.set_direction(mission="Run the studio", change_note="pivot")
    delta = plane.changes_since(1).delta

    assert any("Run the agency" in line and "Run the studio" in line for line in delta)


def test_an_added_principle_is_named_as_added(plane):
    plane.set_direction(
        principles=(
            "Craft first",
            "Client success over billable hours",
            "Honest scoping",
            "Ship weekly",
        ),
        change_note="new principle",
    )
    delta = plane.changes_since(1).delta

    assert len(delta) == 1
    assert "Ship weekly" in delta[0]
    assert "added" in delta[0].lower()


def test_a_dropped_principle_is_named_as_dropped(plane):
    plane.set_direction(principles=("Craft first", "Honest scoping"), change_note="retire one")
    delta = plane.changes_since(1).delta

    assert any("Client success over billable hours" in line for line in delta)
    assert any("dropped" in line.lower() for line in delta)


def test_a_consumer_holding_nothing_gets_no_delta(plane):
    """There is no baseline to diff against, and the whole constitution is
    already in front of them."""
    assert plane.changes_since(0).delta == ()


def test_a_consumer_already_current_gets_no_delta(plane):
    assert plane.changes_since(1).delta == ()


def test_the_delta_spans_every_version_the_consumer_missed(plane):
    plane.set_direction(mission="Run the studio", change_note="one")
    plane.set_direction(
        principles=("Craft first", "Retainer outcomes come first", "Honest scoping"),
        change_note="two",
    )
    delta = plane.changes_since(1).delta

    assert any("Run the studio" in line for line in delta)
    assert any("Retainer outcomes come first" in line for line in delta)


def test_the_delta_is_separate_from_the_operator_note(plane):
    """The note carries intent, the delta carries fact. Losing either one
    loses something the other cannot say."""
    plane.set_direction(
        principles=("Craft first", "Retainer outcomes come first", "Honest scoping"),
        change_note="board decision after the Q3 review",
    )
    changes = plane.changes_since(1)

    assert changes.change_notes == ("board decision after the Q3 review",)
    assert changes.delta and "Retainer outcomes come first" in changes.delta[0]


def test_the_injected_block_carries_the_delta(plane):
    from kyno.sdk.binder import DirectionBinder
    from kyno.sdk.client import LocalDirectionSource

    binder = DirectionBinder(LocalDirectionSource(plane))
    binder.bind()
    plane.set_direction(
        principles=("Craft first", "Retainer outcomes come first", "Honest scoping"),
        change_note="board decision",
    )
    rendered = binder.bind().render()

    assert "What changed:" in rendered
    assert "Retainer outcomes come first" in rendered
    assert "Client success over billable hours" in rendered
