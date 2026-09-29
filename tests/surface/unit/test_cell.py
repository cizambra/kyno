import json
import threading
from dataclasses import FrozenInstanceError

import pytest

from kyno.sdk.cell import (
    DIRECTION_MARKER,
    Direction,
    DirectionCell,
    DirectionSnapshot,
)
from kyno.sdk.recording import RecordingReceipt
from kyno.wire.models import ChangesSince, DetailLevel, Principle

RICH = dict(
    constitution_key="eu",
    version=2,
    mission="Ship trustworthy lending",
    declaration="# Our declaration\n\nThe long form of what that means.",
    principles=(Principle("Say the hard number first", "Before any softening story."),),
)


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


def test_given_empty_cache_when_get_runs_then_no_snapshot_is_returned():
    cell = DirectionCell()
    assert cell.last_seen_version() == 0
    assert cell.get() is None


def test_given_cached_version_when_cell_update_receives_older_version_then_cache_is_unchanged():
    cell = DirectionCell()
    cell.update(DirectionSnapshot(_direction(5)))
    held = cell.update(DirectionSnapshot(_direction(2)))
    assert held.direction.version == 5
    assert cell.get().direction.mission == "M5"


def test_given_concurrent_responses_when_cell_update_then_newest_snapshot_is_preserved():
    cell = DirectionCell()
    snapshots = [
        DirectionSnapshot(
            _direction(version),
            RecordingReceipt("recorded", f"receipt-{version}"),
            (f"Intent for version {version}",),
            (f"Delta for version {version}",),
        )
        for version in range(1, 21)
    ]
    threads = [threading.Thread(target=cell.update, args=(snapshot,)) for snapshot in snapshots]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
        assert not t.is_alive()

    assert cell.get() is snapshots[-1]


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


@pytest.mark.parametrize("detail", list(DetailLevel))
def test_given_direction_when_to_dict_runs_then_authoritative_fields_are_json_serializable(detail):
    direction = Direction(
        constitution_key="support",
        version=3,
        mission="Help customers",
        declaration="Explain resolutions.",
        principles=(Principle("Be clear", "Use plain language."),),
        detail=detail,
    )

    payload = direction.to_dict()

    assert json.loads(json.dumps(payload)) == {
        "constitution_key": "support",
        "version": 3,
        "mission": "Help customers",
        "declaration": "Explain resolutions.",
        "principles": [{"title": "Be clear", "description": "Use plain language."}],
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


def test_given_cached_version_zero_when_cell_get_then_empty_direction_and_receipt_return():
    cell = DirectionCell()
    direction = Direction.empty("support")
    receipt = RecordingReceipt("recorded", "empty-direction-record")
    cell.update(DirectionSnapshot(direction, receipt))

    assert cell.get() == DirectionSnapshot(direction, receipt)
    assert cell.last_seen_version() == 0


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


def test_given_cached_snapshot_when_cell_update_receives_older_version_then_metadata_is_unchanged():
    cell = DirectionCell()
    newer = DirectionSnapshot(
        _direction(5), RecordingReceipt("recorded", "newer"), ("New intent",), ("New delta",)
    )
    cell.update(newer)
    older = DirectionSnapshot(
        _direction(2), RecordingReceipt("recorded", "older"), ("Old intent",), ("Old delta",)
    )

    accepted = cell.update(older)

    assert accepted is newer
    assert cell.get() is newer


def test_given_cached_snapshot_when_cell_update_receives_same_version_then_metadata_is_replaced():
    cell = DirectionCell()
    cell.update(DirectionSnapshot(_direction(5), None, ("First intent",), ("First delta",)))
    latest = DirectionSnapshot(_direction(5), RecordingReceipt("recorded", "latest"))

    accepted = cell.update(latest)

    assert accepted is latest
    assert cell.get() is latest


def test_given_mutable_metadata_when_direction_snapshot_init_then_values_are_copied():
    notes = ["Prioritize resolution"]
    delta = ["Mission changed."]

    snapshot = DirectionSnapshot(_direction(2), change_notes=notes, delta=delta)
    notes.append("Caller annotation")
    delta.clear()

    assert snapshot.change_notes == ("Prioritize resolution",)
    assert snapshot.delta == ("Mission changed.",)


def test_given_frozen_snapshot_when_assigning_delta_then_frozen_instance_error_is_raised():
    snapshot = DirectionSnapshot(_direction(2), delta=("Mission changed.",))

    with pytest.raises(FrozenInstanceError):
        snapshot.delta = ("Caller annotation",)
