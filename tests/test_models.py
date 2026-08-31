from datetime import UTC, datetime

import pytest

from kyno.errors import MalformedPrincipleError
from kyno.models import ChangesSince, ConstitutionVersion, Principle, normalize_principles


def test_given_a_version_when_assigning_a_field_then_it_is_frozen_and_still_serializes():
    v = ConstitutionVersion(
        version=1,
        mission="Serve customers",
        principles=(Principle("Be honest"),),
        change_note="initial",
        changed_mission=True,
        changed_principles=True,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        created_by="op",
    )
    assert v.principles == (Principle("Be honest"),)
    d = v.to_dict()
    assert d["principles"] == [{"title": "Be honest", "description": ""}]
    assert d["version"] == 1 and d["created_by"] == "op"


def test_given_changes_since_when_serializing_then_the_notes_are_a_list():
    c = ChangesSince(
        current_version=3,
        changed=True,
        mission="M",
        principles=(Principle("p1"), Principle("p2")),
        changed_mission=False,
        changed_principles=True,
        change_notes=("n2", "n3"),
    )
    d = c.to_dict()
    assert d["change_notes"] == ["n2", "n3"]
    assert d["principles"] == [
        {"title": "p1", "description": ""},
        {"title": "p2", "description": ""},
    ]
    assert d["changed"] is True


# --- principles: a title, and an optional description ----------------------


def test_given_a_plain_string_when_normalizing_then_it_is_a_title_with_no_description():
    assert Principle.of("Be honest") == Principle(title="Be honest", description="")


def test_given_a_mapping_when_normalizing_then_the_description_rides_with_the_title():
    p = Principle.of({"title": "Be honest", "description": "Say the hard number first."})
    assert (p.title, p.description) == ("Be honest", "Say the hard number first.")


def test_given_a_principle_when_normalizing_then_it_passes_through_unchanged():
    p = Principle("Be honest", "Say the hard number first.")
    assert Principle.of(p) is p


def test_given_a_principle_with_an_empty_half_when_serializing_then_both_halves_appear():
    assert Principle("t", "d").to_dict() == {"title": "t", "description": "d"}
    # Deliberate: the key is always present. An absent key would make callers
    # guess, and "" is the honest answer for a principle nobody described.
    assert Principle("t").to_dict() == {"title": "t", "description": ""}


def test_given_principles_differing_only_in_description_when_comparing_then_they_are_not_equal():
    # Load-bearing: equality is what decides whether a set is a real change,
    # so a description-only edit must not read as "nothing moved".
    assert Principle("t", "one") != Principle("t", "two")


def test_given_a_principle_with_no_title_when_normalizing_then_it_is_refused():
    for value in ("", "   ", {"description": "orphan"}, {"title": "  "}):
        with pytest.raises(MalformedPrincipleError):
            Principle.of(value)


def test_given_a_misspelled_principle_key_when_normalizing_then_it_is_refused_not_dropped():
    # A silently ignored "descriptoin" would publish a principle whose
    # paragraph nobody can find.
    with pytest.raises(MalformedPrincipleError, match="descriptoin"):
        Principle.of({"title": "t", "descriptoin": "typo"})


def test_given_a_principle_that_is_neither_text_nor_a_mapping_when_normalizing_then_it_is_refused():
    with pytest.raises(MalformedPrincipleError):
        Principle.of(["Be honest"])


def test_given_a_mixed_sequence_when_normalizing_then_its_order_is_kept():
    got = normalize_principles(["a", {"title": "b", "description": "why b"}, Principle("c")])
    assert got == (Principle("a"), Principle("b", "why b"), Principle("c"))


def test_given_none_when_normalizing_then_it_stays_none_so_carry_forward_is_untouched():
    assert normalize_principles(None) is None


# --- the declaration -------------------------------------------------------


def test_given_a_version_without_a_declaration_when_reading_then_it_carries_an_empty_one():
    v = ConstitutionVersion(
        version=1,
        mission="M",
        principles=(),
        change_note="init",
        changed_mission=True,
        changed_principles=True,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        created_by=None,
    )
    assert v.declaration == ""
    assert v.to_dict()["declaration"] == ""


def test_given_a_declaration_when_serializing_then_it_sits_beside_the_mission_it_expands():
    v = ConstitutionVersion(
        version=1,
        mission="M",
        principles=(),
        change_note="init",
        changed_mission=True,
        changed_principles=True,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        created_by=None,
        declaration="## Why\n\nBecause the mission is one line.",
    )
    assert v.to_dict()["declaration"] == "## Why\n\nBecause the mission is one line."


def test_given_a_principle_whose_description_is_not_text_when_normalizing_then_it_is_refused():
    with pytest.raises(MalformedPrincipleError, match="must be text"):
        normalize_principles(({"title": "t", "description": 123},))
