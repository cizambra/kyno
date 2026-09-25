import json
import threading

import pytest

from kyno.sdk.cell import (
    DIRECTION_MARKER,
    Direction,
    DirectionCell,
)
from kyno.sdk.recording import RecordingReceipt
from kyno.wire.models import ChangesSince, DetailLevel, Principle


def _direction(version: int, constitution: str = "default") -> Direction:
    return Direction(
        constitution=constitution,
        version=version,
        mission=f"M{version}",
        principles=("p1",),
    )


@pytest.mark.parametrize("key", [None, "", "Upper", "bad/name", " sup port "])
def test_given_invalid_key_when_creating_direction_then_it_is_rejected(key):
    with pytest.raises(ValueError, match="constitution key"):
        _direction(1, key)


def test_given_changes_when_building_a_direction_then_the_constitution_name_is_carried():
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


def test_given_the_empty_direction_when_comparing_then_it_matches_version_zero():
    d = Direction.empty("eu")
    assert (d.version, d.mission, d.principles) == (0, "", ())


def test_given_a_direction_when_rendering_then_the_constitution_and_version_are_named():
    block = _direction(2, "eu").render()
    assert block.startswith(DIRECTION_MARKER)
    assert "constitution=eu" in block and "version=2" in block
    assert "M2" in block and "p1" in block


def test_given_empty_cache_when_get_with_recording_runs_then_no_snapshot_is_returned():
    cell = DirectionCell()
    assert cell.last_seen_version() == 0
    assert cell.get_with_recording() is None


def test_given_an_older_version_when_updating_the_cell_then_it_never_regresses():
    cell = DirectionCell()
    cell.update_with_recording(_direction(5))
    held, _recording = cell.update_with_recording(_direction(2))
    assert held.version == 5 and cell.get_with_recording()[0].mission == "M5"


def test_given_concurrent_updates_when_racing_the_cell_then_the_newest_version_holds():
    cell = DirectionCell()
    threads = [
        threading.Thread(target=cell.update_with_recording, args=(_direction(version),))
        for version in range(1, 21)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert cell.get_with_recording()[0].version == 20
    assert cell.get_with_recording()[0].mission == "M20"


def test_given_the_injected_block_when_reading_then_titles_come_without_descriptions():
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


def test_given_plain_strings_when_building_a_direction_then_principles_still_hold():
    # Every caller that passed strings before keeps working; they become titles.
    d = Direction(constitution="eu", version=1, mission="M", principles=("p1",))
    assert d.principles == (Principle("p1"),)


@pytest.mark.parametrize("delta", [(), ("Mission changed.", "Principle added.")])
@pytest.mark.parametrize("detail", list(DetailLevel))
def test_given_direction_with_changes_when_to_dict_runs_then_all_fields_are_json_serializable(
    delta, detail
):
    direction = Direction(
        constitution="support",
        version=3,
        mission="Help customers",
        declaration="Explain resolutions.",
        principles=(Principle("Be clear", "Use plain language."),),
        change_notes=("Prioritize support",),
        delta=delta,
        detail=detail,
    )

    payload = direction.to_dict()

    assert json.loads(json.dumps(payload)) == {
        "constitution": "support",
        "version": 3,
        "mission": "Help customers",
        "declaration": "Explain resolutions.",
        "principles": [{"title": "Be clear", "description": "Use plain language."}],
        "change_notes": ["Prioritize support"],
        "delta": list(delta),
        "detail": detail.value,
    }
    payload["delta"].append("Caller annotation")
    assert direction.delta == delta


def test_given_a_direction_when_serializing_then_principles_come_in_full():
    d = Direction(
        constitution="eu",
        version=1,
        mission="M",
        principles=(Principle("t", "d"),),
    )
    assert d.to_dict()["principles"] == [{"title": "t", "description": "d"}]


def test_given_the_injected_block_when_reading_then_the_declaration_is_left_out():
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


def test_given_a_direction_when_reading_then_the_declaration_is_there_for_the_full_text():
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


# --- how much detail the injected block carries ---------------------------

RICH = dict(
    constitution="eu",
    version=2,
    mission="Ship trustworthy lending",
    declaration="# Our declaration\n\nThe long form of what that means.",
    principles=(Principle("Say the hard number first", "Before any softening story."),),
)


def test_given_full_detail_when_render_is_called_then_declaration_and_descriptions_are_included():
    # The opt-in: an organization that would rather spend tokens on detail
    # gets the whole document in the block, not just the handles.
    block = Direction(**RICH, detail=DetailLevel.FULL).render()
    assert "The long form of what that means." in block
    assert "Say the hard number first" in block
    assert "Before any softening story." in block


def test_given_default_detail_when_direction_is_constructed_then_detail_is_compact():
    assert Direction(**RICH).detail is DetailLevel.COMPACT
    assert "Before any softening story." not in Direction(**RICH).render()


def test_given_full_detail_string_when_direction_is_constructed_then_detail_is_typed():
    assert Direction(**RICH, detail="full").detail is DetailLevel.FULL


def test_given_full_detail_when_direction_to_dict_is_called_then_detail_is_a_plain_string():
    payload = Direction(**RICH, detail=DetailLevel.FULL).to_dict()

    assert payload["detail"] == "full"
    assert type(payload["detail"]) is str


def test_given_a_full_block_when_reading_then_each_description_sits_under_its_title():
    lines = Direction(**RICH, detail=DetailLevel.FULL).render().splitlines()
    title_at = lines.index("- Say the hard number first")
    assert lines[title_at + 1].strip() == "Before any softening story."


def test_given_unknown_detail_when_direction_is_constructed_then_value_error_is_raised():
    with pytest.raises(ValueError, match="verbose"):
        Direction(**RICH, detail="verbose")


def test_given_cached_version_zero_when_get_with_recording_runs_then_empty_direction_is_retained():
    cell = DirectionCell()
    direction = Direction.empty("support")
    receipt = RecordingReceipt("recorded", "empty-direction-record")
    cell.update_with_recording(direction, receipt)

    assert cell.get_with_recording() == (direction, receipt)
    assert cell.last_seen_version() == 0
