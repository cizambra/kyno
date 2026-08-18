from datetime import UTC, datetime

import pytest

from kyno.errors import MalformedPrincipleError
from kyno.models import ChangesSince, ConstitutionVersion, Principle, normalize_principles


def test_version_is_frozen_and_serializes():
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


def test_changes_since_serializes_notes_as_list():
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


def test_a_plain_string_is_a_title_with_no_description():
    assert Principle.of("Be honest") == Principle(title="Be honest", description="")


def test_a_mapping_carries_the_description_with_the_title():
    p = Principle.of({"title": "Be honest", "description": "Say the hard number first."})
    assert (p.title, p.description) == ("Be honest", "Say the hard number first.")


def test_a_principle_passes_through_unchanged():
    p = Principle("Be honest", "Say the hard number first.")
    assert Principle.of(p) is p


def test_a_principle_serializes_both_halves_even_when_one_is_empty():
    assert Principle("t", "d").to_dict() == {"title": "t", "description": "d"}
    # Deliberate: the key is always present. An absent key would make callers
    # guess, and "" is the honest answer for a principle nobody described.
    assert Principle("t").to_dict() == {"title": "t", "description": ""}


def test_two_principles_differing_only_in_description_are_not_equal():
    # Load-bearing: equality is what decides whether a set is a real change,
    # so a description-only edit must not read as "nothing moved".
    assert Principle("t", "one") != Principle("t", "two")


def test_a_principle_with_no_title_is_refused():
    for value in ("", "   ", {"description": "orphan"}, {"title": "  "}):
        with pytest.raises(MalformedPrincipleError):
            Principle.of(value)


def test_a_misspelled_principle_key_is_refused_rather_than_dropped():
    # A silently ignored "descriptoin" would publish a principle whose
    # paragraph nobody can find.
    with pytest.raises(MalformedPrincipleError, match="descriptoin"):
        Principle.of({"title": "t", "descriptoin": "typo"})


def test_a_principle_that_is_neither_text_nor_a_mapping_is_refused():
    with pytest.raises(MalformedPrincipleError):
        Principle.of(["Be honest"])


def test_normalizing_accepts_a_mixed_sequence_and_keeps_its_order():
    got = normalize_principles(["a", {"title": "b", "description": "why b"}, Principle("c")])
    assert got == (Principle("a"), Principle("b", "why b"), Principle("c"))


def test_normalizing_none_stays_none_so_carry_forward_is_untouched():
    assert normalize_principles(None) is None


# --- the declaration -------------------------------------------------------


def test_a_version_without_a_declaration_carries_an_empty_one():
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


def test_a_declaration_serializes_beside_the_mission_it_expands():
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
