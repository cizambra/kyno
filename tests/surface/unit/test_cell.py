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
        constitution_key=constitution,
        version=version,
        mission=f"M{version}",
        principles=("p1",),
    )


@pytest.mark.parametrize("key", ["", "Upper", "bad/name", " sup port ", "a" * 201])
def test_given_invalid_constitution_key_when_direction_init_then_it_is_rejected(key):
    with pytest.raises(ValueError, match="constitution key"):
        _direction(1, key)


def test_given_padded_200_character_key_when_direction_init_then_full_key_is_preserved():
    key = "a" * 200
    assert _direction(1, f" {key} ").constitution_key == key


def test_given_key_and_changes_when_direction_from_changes_then_identity_and_content_match():
    changes = ChangesSince(
        constitution_key="default",
        current_version=3,
        changed=True,
        mission="Ship trustworthy lending",
        principles=(Principle("Be honest"),),
        changed_mission=True,
        changed_principles=False,
        change_notes=("pivot",),
    )
    direction = Direction.from_changes(changes, constitution_key="eu")

    assert direction.constitution_key == "eu"
    assert direction.version == 3
    assert direction.mission == "Ship trustworthy lending"
    assert direction.principles == (Principle("Be honest"),)
    assert direction.change_notes == ("pivot",)


def test_given_the_empty_direction_when_direction_empty_then_it_matches_version_zero():
    d = Direction.empty(constitution_key="eu")
    assert d.constitution_key == "eu"
    assert d.version == 0
    assert d.mission == ""
    assert d.principles == ()


def test_given_a_direction_when_direction_render_then_the_constitution_and_version_are_named():
    block = _direction(2, "eu").render()
    assert block.startswith(DIRECTION_MARKER)
    assert "constitution_key=eu" in block
    assert "version=2" in block
    assert "M2" in block
    assert "p1" in block


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


def test_given_default_detail_when_direction_render_runs_then_long_text_is_excluded():
    # Deliberate: the block is injected at every step, so compact rendering
    # excludes the longer text. Callers can request full detail when needed.
    direction = Direction(
        constitution_key="eu",
        version=2,
        mission="Ship trustworthy lending",
        principles=(Principle("Be honest", "Say the hard number first."),),
        declaration="Explain lending decisions in full.",
    )

    block = direction.render()

    assert "Ship trustworthy lending" in block
    assert "Be honest" in block
    assert "Say the hard number first." not in block
    assert "Explain lending decisions in full." not in block
    assert "declaration" not in block.lower()


def test_given_string_principles_when_direction_init_runs_then_strings_become_principle_titles():
    d = Direction(constitution_key="eu", version=1, mission="M", principles=("p1",))
    assert d.principles == (Principle("p1"),)


@pytest.mark.parametrize("delta", [(), ("Mission changed.", "Principle added.")])
@pytest.mark.parametrize("detail", list(DetailLevel))
def test_given_direction_with_changes_when_to_dict_runs_then_all_fields_are_json_serializable(
    delta, detail
):
    direction = Direction(
        constitution_key="support",
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
        "constitution_key": "support",
        "version": 3,
        "mission": "Help customers",
        "declaration": "Explain resolutions.",
        "principles": [{"title": "Be clear", "description": "Use plain language."}],
        "change_notes": ["Prioritize support"],
        "delta": list(delta),
        "detail": detail.value,
    }


def test_given_a_direction_when_direction_to_dict_then_principles_come_in_full():
    d = Direction(
        constitution_key="eu",
        version=1,
        mission="M",
        principles=(Principle("t", "d"),),
    )
    assert d.to_dict()["principles"] == [{"title": "t", "description": "d"}]


def test_given_declaration_in_changes_when_direction_from_changes_then_declaration_is_preserved():
    changes = ChangesSince(
        constitution_key="default",
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
    constitution_key="eu",
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


def test_given_serialized_delta_when_caller_appends_to_list_then_direction_delta_is_unchanged():
    direction = Direction(
        constitution_key="support",
        version=2,
        mission="Help customers",
        principles=(),
        delta=("Mission changed.",),
    )
    payload = direction.to_dict()

    payload["delta"].append("Caller annotation")

    assert payload["delta"] == ["Mission changed.", "Caller annotation"]
    assert direction.delta == ("Mission changed.",)


@pytest.mark.parametrize("key", [1, True, [], {}, "", " ", "Upper", "bad/name", "a" * 201])
def test_given_invalid_constitution_key_when_direction_empty_then_value_error_is_raised(key):
    with pytest.raises(ValueError, match="constitution key"):
        Direction.empty(key)


@pytest.mark.parametrize("key", [None, 1, True, [], {}, "", " ", "Upper", "bad/name", "a" * 201])
def test_given_invalid_constitution_key_when_direction_from_changes_then_value_error_is_raised(key):
    changes = ChangesSince(
        constitution_key="support",
        current_version=1,
        changed=True,
        mission="Help customers",
        principles=(),
        changed_mission=True,
        changed_principles=False,
        change_notes=(),
    )

    with pytest.raises(ValueError, match="constitution key"):
        Direction.from_changes(changes, constitution_key=key)


@pytest.mark.parametrize("key", ["support", "a" * 200], ids=["named-key", "maximum-length-key"])
def test_given_padded_key_when_direction_from_changes_runs_then_trimmed_key_is_retained(key):
    changes = ChangesSince(
        constitution_key=key,
        current_version=1,
        changed=True,
        mission="Help customers",
        principles=(),
        changed_mission=True,
        changed_principles=False,
        change_notes=(),
    )

    direction = Direction.from_changes(changes, constitution_key=f" \t{key}\n")

    assert direction.constitution_key == key


def test_given_written_direction_without_constitution_key_when_direction_init_then_rejected():
    with pytest.raises(ValueError, match="resolved constitution key"):
        Direction(constitution_key=None, version=1, mission="Help", principles=())


def test_given_no_constitution_key_when_direction_empty_then_version_zero_has_no_constitution_key():
    direction = Direction.empty(None)

    assert direction.constitution_key is None
    assert direction.version == 0
    assert direction.mission == ""
    assert direction.principles == ()


def test_given_direction_without_constitution_key_when_to_dict_then_constitution_key_is_none():
    direction = Direction.empty(None)

    payload = direction.to_dict()

    assert payload["constitution_key"] is None


def test_given_direction_without_constitution_key_when_render_then_header_omits_constitution_key():
    direction = Direction.empty(None)

    block = direction.render()

    assert block == "[kyno:direction version=0]\nNo direction has been received yet."
