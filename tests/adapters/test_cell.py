import threading

import pytest

from kyno.models import ChangesSince, Principle
from kyno.sdk.cell import (
    COMPACT,
    DIRECTION_MARKER,
    FULL,
    Direction,
    DirectionCell,
)


def _direction(version: int, constitution: str = "default") -> Direction:
    return Direction(
        constitution=constitution,
        version=version,
        mission=f"M{version}",
        principles=("p1",),
    )


def test_direction_from_changes_carries_the_constitution_name():
    changes = ChangesSince(
        current_version=3,
        changed=True,
        mission="Ship trustworthy lending",
        principles=(Principle("Be honest"),),
        changed_mission=True,
        changed_principles=False,
        change_notes=("pivot",),
    )
    d = Direction.from_changes(changes, "eu")
    assert d.constitution == "eu" and d.version == 3
    assert d.principles == (Principle("Be honest"),) and d.change_notes == ("pivot",)


def test_empty_direction_matches_the_control_planes_version_zero_state():
    d = Direction.empty("eu")
    assert (d.version, d.mission, d.principles) == (0, "", ())


def test_render_names_the_constitution_and_version():
    block = _direction(2, "eu").render()
    assert block.startswith(DIRECTION_MARKER)
    assert "constitution=eu" in block and "version=2" in block
    assert "M2" in block and "p1" in block


def test_cell_is_keyed_by_constitution_name():
    cell = DirectionCell()
    cell.update(_direction(1, "eu"))
    cell.update(_direction(7, "us"))
    assert cell.known_version("eu") == 1
    assert cell.known_version("us") == 7
    assert cell.known_version("never-written") == 0
    assert cell.get("never-written") is None
    assert cell.names() == ("eu", "us")


def test_cell_never_regresses_to_an_older_version():
    cell = DirectionCell()
    cell.update(_direction(5))
    held = cell.update(_direction(2))
    assert held.version == 5 and cell.get("default").mission == "M5"


def test_cell_holds_the_newest_version_under_concurrent_updates():
    # Real concurrency, because monotonicity is the invariant under test. The assertion
    # holds under every interleaving: update() keeps the max, so whatever
    # order the threads land in, the cell ends at 20.
    cell = DirectionCell()
    threads = [threading.Thread(target=cell.update, args=(_direction(v),)) for v in range(1, 21)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert cell.get("default").version == 20
    assert cell.get("default").mission == "M20"


def test_the_injected_block_carries_principle_titles_and_not_their_descriptions():
    # Deliberate, and it is about what this costs: the block is re-injected at
    # every step boundary, so the paragraphs stay out of it. An agent that needs
    # the full text reads get_constitution or the published page.
    direction = Direction(
        constitution="eu",
        version=2,
        mission="Ship trustworthy lending",
        principles=(Principle("Say the hard number first", "Before any softening story."),),
    )
    block = direction.render()
    assert "Say the hard number first" in block
    assert "Before any softening story." not in block


def test_a_direction_built_from_plain_strings_still_holds_principles():
    # Every caller that passed strings before keeps working; they become titles.
    d = Direction(constitution="eu", version=1, mission="M", principles=("p1",))
    assert d.principles == (Principle("p1"),)


def test_a_direction_serializes_principles_in_full():
    d = Direction(
        constitution="eu",
        version=1,
        mission="M",
        principles=(Principle("t", "d"),),
    )
    assert d.to_dict()["principles"] == [{"title": "t", "description": "d"}]


def test_the_injected_block_leaves_the_declaration_out():
    # Same cost rule as leaving descriptions out: a declaration is a document,
    # and a document has no business in a block re-sent at every step boundary.
    direction = Direction(
        constitution="eu",
        version=2,
        mission="Ship trustworthy lending",
        principles=(Principle("Be honest"),),
        declaration="# Our declaration\n\nA long document nobody should pay for twice.",
    )
    block = direction.render()
    assert "Ship trustworthy lending" in block
    assert "A long document" not in block
    assert "declaration" not in block.lower()


def test_a_direction_carries_the_declaration_for_whoever_wants_the_full_text():
    changes = ChangesSince(
        current_version=3,
        changed=True,
        mission="M",
        principles=(),
        changed_mission=True,
        changed_principles=False,
        change_notes=(),
        declaration="The long form.",
    )
    assert Direction.from_changes(changes, "eu").declaration == "The long form."


# --- how much context the injected block carries ---------------------------

RICH = dict(
    constitution="eu",
    version=2,
    mission="Ship trustworthy lending",
    declaration="# Our declaration\n\nThe long form of what that means.",
    principles=(Principle("Say the hard number first", "Before any softening story."),),
)


def test_the_full_context_injects_the_declaration_and_the_descriptions():
    # The opt-in: an organization that would rather spend tokens on context
    # gets the whole document in the block, not just the handles.
    block = Direction(**RICH, context=FULL).render()
    assert "The long form of what that means." in block
    assert "Say the hard number first" in block
    assert "Before any softening story." in block


def test_the_compact_context_is_what_a_direction_carries_unless_asked():
    assert Direction(**RICH).context == COMPACT
    assert "Before any softening story." not in Direction(**RICH).render()


def test_a_full_block_keeps_a_description_under_the_title_it_explains():
    lines = Direction(**RICH, context=FULL).render().splitlines()
    title_at = lines.index("- Say the hard number first")
    assert lines[title_at + 1].strip() == "Before any softening story."


def test_an_unknown_context_is_refused_where_it_is_set():
    with pytest.raises(ValueError, match="verbose"):
        Direction(**RICH, context="verbose")
