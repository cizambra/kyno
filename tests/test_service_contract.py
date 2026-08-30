from datetime import UTC, datetime

import pytest

from kyno.errors import (
    EmptyChangeError,
    MalformedPrincipleError,
    UnknownConstitutionError,
    UnknownVersionError,
    UnpublishableNameError,
    VersionConflictError,
)
from kyno.models import Principle
from kyno.service import ControlPlane
from kyno.store.sql import SqlConstitutionStore


class AlwaysConflictStore:
    """A store whose append() always raises VersionConflictError, to trigger
    ControlPlane's retry-exhaustion behavior without needing real
    contention."""

    def __init__(self):
        self.append_calls = 0

    def head(self, constitution):
        return None

    def get(self, constitution, version):
        return None

    def versions_after(self, constitution, known_version):
        return []

    def append(self, *args, **kwargs):
        self.append_calls += 1
        raise VersionConflictError("simulated permanent race")


@pytest.fixture
def cp():
    store = SqlConstitutionStore(url="sqlite://")
    store.create_all()
    return ControlPlane(store)


def test_given_an_uninitialized_store_when_reading_current_then_the_empty_state_returns(cp):
    v = cp.current()
    assert v.version == 0
    assert v.mission == ""
    assert v.principles == ()


def test_given_an_empty_store_when_asking_changes_since_then_zero_changes_return(cp):
    c = cp.changes_since(0)
    assert c.current_version == 0
    assert c.changed is False
    assert c.mission == ""
    assert c.principles == ()
    assert c.changed_mission is False
    assert c.changed_principles is False
    assert c.change_notes == ()


def test_given_an_empty_store_when_asking_changes_since_any_version_then_it_does_not_raise(cp):
    # No HEAD to compare against on an empty store, so no known_version
    # can be "in the future" -- never UnknownVersionError.
    c = cp.changes_since(5)
    assert c.current_version == 0
    assert c.changed is False


def test_given_prior_empty_reads_when_writing_the_first_version_then_it_is_still_v1(cp):
    assert cp.current().version == 0
    assert cp.changes_since(0).current_version == 0
    v = cp.set_direction(mission="M1", principles=("p1",), change_note="init")
    assert v.version == 1
    assert cp.current().version == 1
    assert cp.current().mission == "M1"


def test_given_a_fresh_store_when_setting_direction_first_then_v1_marks_all_changed(cp):
    v = cp.set_direction(mission="M1", principles=("p1",), change_note="init", created_by="op")
    assert v.version == 1 and v.changed_mission and v.changed_principles
    assert cp.current().mission == "M1"


def test_given_omitted_fields_when_setting_direction_then_they_carry_forward(cp):
    cp.set_direction(mission="M1", principles=("p1",), change_note="init")
    v2 = cp.set_direction(principles=("p1", "p2"), change_note="add p2")
    assert v2.mission == "M1"
    assert v2.changed_mission is False
    assert v2.changed_principles is True
    assert v2.principles == (Principle("p1"), Principle("p2"))


def test_given_identical_content_when_setting_direction_then_the_no_op_is_rejected(cp):
    cp.set_direction(mission="M1", principles=("p1",), change_note="init")
    with pytest.raises(EmptyChangeError):
        cp.set_direction(mission="M1", principles=("p1",), change_note="noop")


def test_given_the_current_version_when_asking_changes_since_then_it_reports_unchanged(cp):
    cp.set_direction(mission="M1", principles=("p1",), change_note="init")
    c = cp.changes_since(1)
    assert c.changed is False and c.current_version == 1


def test_given_several_versions_when_asking_changes_since_then_notes_and_flags_aggregate(cp):
    cp.set_direction(mission="M1", principles=("p1",), change_note="init")
    cp.set_direction(mission="M2", change_note="pivot mission")
    cp.set_direction(principles=("p1", "p2"), change_note="add p2")
    c = cp.changes_since(1)
    assert c.current_version == 3 and c.changed is True
    assert c.mission == "M2" and c.principles == (Principle("p1"), Principle("p2"))
    assert c.changed_mission is True and c.changed_principles is True
    assert c.change_notes == ("pivot mission", "add p2")


def test_given_version_zero_when_asking_changes_since_then_the_full_current_returns(cp):
    cp.set_direction(mission="M1", principles=("p1",), change_note="init")
    c = cp.changes_since(0)
    assert c.changed is True and c.current_version == 1
    assert c.change_notes == ("init",)


def test_given_a_future_version_when_asking_changes_since_then_it_raises(cp):
    cp.set_direction(mission="M1", principles=("p1",), change_note="init")
    with pytest.raises(UnknownVersionError):
        cp.changes_since(5)


def test_given_a_subscriber_when_a_write_commits_then_on_change_fires_after(cp):
    seen = []
    cp.on_change(lambda v: seen.append(v.version))
    cp.set_direction(mission="M1", principles=("p1",), change_note="init")
    cp.set_direction(mission="M2", change_note="pivot")
    assert seen == [1, 2]


def test_given_a_racing_writer_when_applying_then_a_conflict_surfaces_not_a_recompute():
    real = SqlConstitutionStore(url="sqlite://")
    real.create_all()
    ControlPlane(real).set_direction(mission="M1", principles=("p1",), change_note="init")

    class ConflictOnceStore:
        """Delegates to a real store, but the first append() simulates a
        concurrent writer taking the next version, then raises
        VersionConflictError — forcing ControlPlane to re-read head and retry."""

        def __init__(self, inner):
            self.inner = inner
            self.raised = False

        def head(self, constitution):
            return self.inner.head(constitution)

        def get(self, constitution, version):
            return self.inner.get(constitution, version)

        def versions_after(self, constitution, known_version):
            return self.inner.versions_after(constitution, known_version)

        def append(self, *args, **kwargs):
            if not self.raised:
                self.raised = True
                self.inner.append(
                    "default",
                    2,
                    mission="M1",
                    principles=("p1", "concurrent"),
                    change_note="race",
                    changed_mission=False,
                    changed_principles=True,
                    created_by=None,
                )
                raise VersionConflictError("simulated race")
            return self.inner.append(*args, **kwargs)

    cp = ControlPlane(ConflictOnceStore(real))
    # A concurrent writer took the version. Nothing lands and nothing is
    # silently recomputed: the conflict surfaces, and the head is the
    # concurrent writer's edit, untouched.
    with pytest.raises(VersionConflictError, match="moved while applying"):
        cp.set_direction(mission="M2", change_note="pivot after race")
    head = real.head("default")
    assert head.version == 2
    assert head.principles == (Principle("p1"), Principle("concurrent"))


def test_given_a_conflict_when_applying_then_there_is_one_attempt_never_a_loop():
    stub = AlwaysConflictStore()
    cp = ControlPlane(stub)
    with pytest.raises(VersionConflictError):
        cp.set_direction(mission="M", change_note="x")
    assert stub.append_calls == 1


def test_given_a_whitespace_only_change_note_when_setting_direction_then_it_is_rejected(cp):
    # Service strips before checking emptiness (change_note.strip()); a
    # whitespace-only note must raise the same as a truly empty one.
    with pytest.raises(EmptyChangeError):
        cp.set_direction(mission="M1", change_note="   ")


def test_given_a_negative_known_version_when_asking_changes_since_then_it_behaves_as_zero(cp):
    # Deliberate: a negative known_version clamps to the same floor as 0, rather
    # than being treated as "future".
    cp.set_direction(mission="M1", principles=("p1",), change_note="init")
    assert cp.changes_since(-1) == cp.changes_since(0)


def test_given_an_empty_principles_tuple_when_setting_direction_then_the_list_clears(cp):
    # Deliberate: principles=() is a real, present value (distinct from None /
    # "carry forward"), so it clears an existing list rather than being ignored.
    cp.set_direction(mission="M1", principles=("p1", "p2"), change_note="init")
    v2 = cp.set_direction(principles=(), change_note="clear principles")
    assert v2.principles == ()
    assert v2.changed_principles is True


def test_given_a_raising_subscriber_when_writing_then_the_exception_propagates_after_commit(cp):
    # Deliberate: in-process on_change hooks are NOT isolated -- a raising subscriber
    # propagates straight to the caller, after the write already committed.
    # (The MCP layer's own notify hook swallows exceptions instead.)
    def bad_subscriber(_version):
        raise RuntimeError("subscriber blew up")

    cp.on_change(bad_subscriber)
    with pytest.raises(RuntimeError, match="subscriber blew up"):
        cp.set_direction(mission="M1", change_note="init")
    assert cp.current().version == 1
    assert cp.current().mission == "M1"


def test_given_all_empty_fields_when_setting_direction_then_an_empty_v1_is_allowed(cp):
    # Current behavior, kept intentionally. Whether an all-empty v1 should be
    # rejected instead is still an open design question.
    v = cp.set_direction(change_note="x")
    assert v.version == 1
    assert v.mission == ""
    assert v.principles == ()


def test_given_a_previous_version_when_writing_then_changed_flags_compare_against_it():
    store = SqlConstitutionStore(url="sqlite://")
    store.create_all()
    cp = ControlPlane(store)
    cp.set_direction(mission="M1", principles=("p1",), change_note="init")
    v2 = cp.set_direction(mission="M2", change_note="mission only")
    assert v2.changed_mission is True and v2.changed_principles is False
    v3 = cp.set_direction(principles=("p1", "p2"), change_note="principles only")
    assert v3.changed_mission is False and v3.changed_principles is True


def test_given_named_constitutions_when_writing_to_each_then_sequences_stay_independent(cp):
    cp.set_direction(mission="M1", change_note="default init")
    eu = cp.set_direction(mission="EU1", change_note="eu init", constitution="eu")
    assert eu.version == 1
    assert cp.current().version == 1 and cp.current().mission == "M1"
    assert cp.current("eu").version == 1 and cp.current("eu").mission == "EU1"
    assert cp.set_direction(mission="EU2", change_note="eu pivot", constitution="eu").version == 2
    assert cp.current().version == 1


def test_given_a_per_call_name_when_writing_then_the_control_plane_keeps_its_default(cp):
    """Deliberate: the name is per call, not state — one named write must not
    silently redirect every later read on the same control plane."""
    cp.set_direction(mission="EU1", change_note="eu init", constitution="eu")
    assert cp.current().version == 0
    assert cp.changes_since(0).current_version == 0


def test_given_no_name_when_calling_then_the_constructor_name_is_the_fallback(store):
    """Backward compatibility: a control plane pinned to one constitution keeps
    behaving as it did before any call took a name."""
    cp = ControlPlane(store, constitution="eu")
    cp.set_direction(mission="EU1", change_note="init")
    assert cp.current().mission == "EU1"
    assert store.head("eu").mission == "EU1"
    assert store.head("default") is None


def test_given_an_unknown_constitution_when_reading_then_the_empty_state_returns(cp):
    cp.set_direction(mission="M1", change_note="init")
    unknown = cp.current("never-written")
    assert unknown.version == 0 and unknown.mission == "" and unknown.principles == ()
    changes = cp.changes_since(3, constitution="never-written")
    assert changes.current_version == 0 and changes.changed is False


def _plane():
    store = SqlConstitutionStore(url="sqlite://")
    store.create_all()
    return ControlPlane(store)


def _direction(cp, constitution="default", mission="M1", principles=("p1", "p2"), note="init"):
    return cp.set_direction(
        mission=mission, principles=principles, change_note=note, constitution=constitution
    )


def test_given_a_written_constitution_when_not_yet_published_then_it_is_private():
    cp = _plane()
    _direction(cp)
    assert cp.publication().published is False
    assert cp.public_constitution() is None


def test_given_a_publish_when_reading_the_public_view_then_direction_shows_not_history():
    cp = _plane()
    _direction(cp)
    _direction(cp, mission="M2", note="pivot")
    cp.publish()

    public = cp.public_constitution()
    assert public.mission == "M2"
    assert public.principles == (Principle("p1"), Principle("p2"))
    assert public.version == 2
    assert public.history is None


def test_given_a_publish_when_history_is_wanted_then_it_is_a_separate_act():
    # A change note routinely carries internal reasoning, so one flag that
    # exposed both would leak it the first time anyone published.
    cp = _plane()
    _direction(cp)
    _direction(cp, mission="M2", note="dropped a principle for the enterprise deal")
    cp.publish(with_history=True)

    public = cp.public_constitution()
    assert [v.version for v in public.history] == [2, 1]
    assert public.history[0].change_note == "dropped a principle for the enterprise deal"


def test_given_public_history_when_republishing_without_it_then_history_goes_private_again():
    cp = _plane()
    _direction(cp)
    cp.publish(with_history=True)
    cp.publish()
    assert cp.public_constitution().history is None


def test_given_a_published_name_when_unpublishing_then_the_page_goes_away_entirely():
    cp = _plane()
    _direction(cp)
    cp.publish(with_history=True)
    cp.unpublish()
    assert cp.public_constitution() is None
    assert cp.publication().published is False
    assert cp.publication().history_public is False


def test_given_a_republish_when_reading_published_at_then_the_original_stamp_stays():
    # The stamp records when this constitution went public; turning history on
    # later is not a new publication and must not rewrite that.
    cp = _plane()
    _direction(cp)
    first = cp.publish().published_at
    again = cp.publish(with_history=True)
    assert again.published_at == first
    assert again.history_public is True


def test_given_no_direction_when_publishing_then_it_is_an_error():
    # Publishing an empty name would serve a blank page under a real URL.
    cp = _plane()
    with pytest.raises(UnknownConstitutionError):
        cp.publish(constitution="never-written")


def test_given_a_constitution_that_does_not_exist_when_unpublishing_then_it_is_an_error():
    # A typo must not report success while the real page stays public.
    cp = _plane()
    _direction(cp)
    with pytest.raises(UnknownConstitutionError):
        cp.unpublish(constitution="defualt")
    assert cp.publication().published is False


def test_given_several_names_when_publishing_then_publication_is_per_name():
    cp = _plane()
    _direction(cp, "internal", mission="Internal mission")
    _direction(cp, "product", mission="Product mission")
    _direction(cp, "eu", mission="EU mission")
    cp.publish(constitution="product", with_history=True)
    cp.publish(constitution="eu")

    assert cp.public_constitution("internal") is None
    assert cp.public_constitution("product").mission == "Product mission"
    assert cp.public_constitution("product").history is not None
    assert cp.public_constitution("eu").history is None


def test_given_a_mix_of_names_when_listing_published_then_only_the_published_appear():
    cp = _plane()
    _direction(cp, "internal", mission="Internal mission")
    _direction(cp, "product", mission="Product mission")
    cp.publish(constitution="product")

    listed = cp.published_constitutions()
    assert [c.name for c in listed] == ["product"]


def test_given_nothing_published_when_listing_published_then_the_list_is_empty():
    cp = _plane()
    _direction(cp)
    assert cp.published_constitutions() == ()


def test_given_several_published_names_when_listing_then_they_are_ordered_by_name():
    # A stable order keeps the index page deterministic across requests.
    cp = _plane()
    for name in ("zeta", "alpha", "mu"):
        _direction(cp, name, mission=f"{name} mission")
        cp.publish(constitution=name)
    assert [c.name for c in cp.published_constitutions()] == ["alpha", "mu", "zeta"]


def test_given_private_history_when_building_the_public_payload_then_history_is_omitted():
    # An empty list would claim there is no history; the truthful machine-
    # readable answer is that history is simply not on offer.
    cp = _plane()
    _direction(cp)
    cp.publish()
    payload = cp.public_constitution().to_dict()
    assert "history" not in payload
    assert payload["mission"] == "M1"
    assert payload["principles"] == [
        {"title": "p1", "description": ""},
        {"title": "p2", "description": ""},
    ]
    assert payload["version"] == 1
    assert payload["last_changed_at"]


def test_given_public_history_when_building_the_public_payload_then_it_is_newest_first():
    cp = _plane()
    _direction(cp)
    _direction(cp, mission="M2", note="pivot")
    cp.publish(with_history=True)
    payload = cp.public_constitution().to_dict()
    assert [h["version"] for h in payload["history"]] == [2, 1]
    assert payload["history"][0]["change_note"] == "pivot"
    assert payload["constitution"] == "default"


def test_given_a_name_that_cannot_be_a_url_segment_when_publishing_then_it_is_refused():
    # The page is served at /constitutions/<name>. A name with a slash in it
    # would report success and then never be reachable.
    cp = _plane()
    _direction(cp, "acme/eu")
    with pytest.raises(UnpublishableNameError):
        cp.publish(constitution="acme/eu")
    assert cp.publication("acme/eu").published is False


def test_given_a_name_ending_in_json_when_publishing_then_it_is_refused():
    # /constitutions/x.json is the machine-readable route for "x", so a
    # constitution named "x.json" would be served as somebody else.
    cp = _plane()
    _direction(cp, "policy.json")
    with pytest.raises(UnpublishableNameError):
        cp.publish(constitution="policy.json")


def test_given_an_unpublishable_name_when_used_anywhere_else_then_it_still_works():
    # Only publishing is refused; the constitution itself is untouched.
    cp = _plane()
    _direction(cp, "acme/eu", mission="EU mission")
    assert cp.current("acme/eu").mission == "EU mission"
    assert cp.changes_since(0, "acme/eu").mission == "EU mission"


# --- a published name is a slug --------------------------------------------


@pytest.mark.parametrize(
    "name",
    ["acme", "eu", "acme-eu", "acme-eu-west", "policy2", "2026-policy", "index", "a"],
)
def test_given_a_slug_name_when_publishing_then_it_is_accepted(name):
    cp = _plane()
    _direction(cp, name)
    assert cp.publish(constitution=name).published is True


@pytest.mark.parametrize(
    "name",
    [
        "Acme",  # uppercase
        "acme eu",  # space
        "acme?",  # query
        "acme#eu",  # fragment
        "acme%20eu",  # already-encoded
        "acme/eu",  # would leave the path segment
        "policy.json",  # already the machine-readable route for "policy"
        "-acme",  # leading hyphen
        "acme-",  # trailing hyphen
        "acme--eu",  # doubled separator
        "acme_eu",  # underscore
        "acme\n",  # a trailing newline is not the end of the name
        "",
    ],
)
def test_given_a_name_that_is_not_a_slug_when_publishing_then_it_is_refused(name):
    cp = _plane()
    _direction(cp, name)
    with pytest.raises(UnpublishableNameError):
        cp.publish(constitution=name)
    assert cp.publication(name).published is False


def test_given_a_refused_name_when_reading_the_error_then_it_suggests_the_likely_slug():
    # Presentation help only: the suggestion is never applied to the name.
    cp = _plane()
    _direction(cp, "Epicurean Digital")
    with pytest.raises(UnpublishableNameError, match="epicurean-digital"):
        cp.publish(constitution="Epicurean Digital")


def test_given_a_name_with_nothing_sluggable_when_publishing_then_no_suggestion_comes():
    cp = _plane()
    _direction(cp, "///")
    with pytest.raises(UnpublishableNameError, match="cannot be published") as refusal:
        cp.publish(constitution="///")
    assert "like ''" not in str(refusal.value)


def test_given_a_sluggable_name_when_publishing_then_it_is_never_quietly_slugged():
    # The name in the URL is the name agents pass over MCP. Publishing
    # "Acme EU" as "acme-eu" would silently break that identity.
    cp = _plane()
    _direction(cp, "Acme EU")
    with pytest.raises(UnpublishableNameError):
        cp.publish(constitution="Acme EU")
    assert cp.publication("acme-eu").published is False
    assert cp.current("acme-eu").version == 0


def test_given_a_name_refused_for_publishing_when_used_elsewhere_then_it_still_works():
    cp = _plane()
    _direction(cp, "Acme EU", mission="EU mission")
    assert cp.current("Acme EU").mission == "EU mission"
    assert cp.changes_since(0, "Acme EU").mission == "EU mission"


def _publish_bypassing_the_rule(cp, name):
    """A row from before the rule existed: published directly through the
    store, the way a release that predates this check left it."""
    cp._store.set_publication(
        name, published_at=datetime(2026, 1, 1, tzinfo=UTC), history_public=False
    )


def test_given_a_name_published_before_the_rule_when_serving_then_it_works_and_can_go_down():
    # Nobody gets stranded: the rule bites when you publish, and reading or
    # withdrawing a publication never validates.
    cp = _plane()
    _direction(cp, "Legacy Name", mission="Still served")
    _publish_bypassing_the_rule(cp, "Legacy Name")

    public = cp.public_constitution("Legacy Name")
    assert public is not None and public.mission == "Still served"
    assert [v.name for v in cp.published_constitutions()] == ["Legacy Name"]

    assert cp.unpublish(constitution="Legacy Name").published is False
    assert cp.public_constitution("Legacy Name") is None


# --- principles: a title, and an optional description ----------------------


def test_given_plain_strings_when_storing_principles_then_they_are_title_only(cp):
    v = cp.set_direction(mission="M1", principles=("p1", "p2"), change_note="init")
    assert v.principles == (Principle("p1"), Principle("p2"))
    assert all(p.description == "" for p in v.principles)


def test_given_mappings_objects_and_strings_when_setting_principles_then_all_are_accepted(cp):
    v = cp.set_direction(
        principles=(
            "plain",
            {"title": "described", "description": "the paragraph that disambiguates it"},
            Principle("object", "built by hand"),
        ),
        change_note="init",
    )
    assert v.principles == (
        Principle("plain"),
        Principle("described", "the paragraph that disambiguates it"),
        Principle("object", "built by hand"),
    )


def test_given_a_description_only_rewrite_when_setting_direction_then_it_is_a_real_change(cp):
    # The description is the half that disambiguates a principle, so an edit
    # to it must append a version rather than read as "nothing moved".
    cp.set_direction(
        principles=({"title": "Be honest", "description": "first try"},), change_note="init"
    )
    v2 = cp.set_direction(
        principles=({"title": "Be honest", "description": "sharper second try"},),
        change_note="sharpen",
    )
    assert v2.version == 2 and v2.changed_principles is True
    assert v2.principles[0].description == "sharper second try"


def test_given_a_malformed_principle_when_setting_direction_then_it_is_refused_before_append(cp):
    cp.set_direction(mission="M1", change_note="init")
    with pytest.raises(MalformedPrincipleError):
        cp.set_direction(principles=({"description": "no title"},), change_note="bad")
    assert cp.current().version == 1


def test_given_described_principles_when_reading_the_public_view_then_descriptions_show(cp):
    cp.set_direction(
        mission="M1",
        principles=("plain", {"title": "described", "description": "why it matters"}),
        change_note="init",
    )
    cp.publish()
    public = cp.public_constitution()
    assert public.principles == (Principle("plain"), Principle("described", "why it matters"))
    assert public.to_dict()["principles"] == [
        {"title": "plain", "description": ""},
        {"title": "described", "description": "why it matters"},
    ]


# --- the declaration -------------------------------------------------------


def test_given_an_omitted_declaration_when_setting_direction_then_it_carries_forward(cp):
    cp.set_direction(mission="M1", declaration="The long form.", change_note="init")
    v2 = cp.set_direction(mission="M2", change_note="pivot")
    assert v2.declaration == "The long form."


def test_given_an_empty_declaration_when_setting_direction_then_it_clears(cp):
    # Deliberate, and the distinction that matters: omitting it carries the
    # previous one forward, while "" is a present value that removes it.
    cp.set_direction(mission="M1", declaration="The long form.", change_note="init")
    v2 = cp.set_direction(declaration="", change_note="retract the long form")
    assert v2.declaration == ""
    assert cp.current().declaration == ""


def test_given_a_declaration_only_rewrite_when_setting_direction_then_it_is_a_real_change(cp):
    cp.set_direction(mission="M1", declaration="First draft.", change_note="init")
    v2 = cp.set_direction(declaration="Second draft.", change_note="rewrite the long form")
    assert v2.version == 2 and v2.declaration == "Second draft."


def test_given_a_declaration_only_change_when_a_consumer_polls_then_it_reaches_them(cp):
    # The flags stay literally about mission and principles, so `changed` --
    # which is "a version happened" -- is what tells an agent to re-read.
    cp.set_direction(mission="M1", declaration="First draft.", change_note="init")
    cp.set_direction(declaration="Second draft.", change_note="rewrite")
    changes = cp.changes_since(1)
    assert changes.changed is True
    assert changes.declaration == "Second draft."
    assert changes.change_notes == ("rewrite",)


def test_given_an_unchanged_declaration_when_setting_direction_then_it_is_still_no_change(cp):
    cp.set_direction(mission="M1", declaration="Same.", change_note="init")
    with pytest.raises(EmptyChangeError):
        cp.set_direction(mission="M1", declaration="Same.", change_note="noop")


def test_given_the_empty_state_when_reading_then_there_is_no_declaration(cp):
    assert cp.current().declaration == ""
    assert cp.changes_since(0).declaration == ""


def test_given_a_declaration_when_reading_the_public_view_then_it_is_there(cp):
    cp.set_direction(mission="M1", declaration="The long form.", change_note="init")
    cp.publish()
    assert cp.public_constitution().declaration == "The long form."
    assert cp.public_constitution().to_dict()["declaration"] == "The long form."


def test_given_a_head_when_asking_head_and_delta_then_both_come_from_one_read():
    from kyno.service import ControlPlane
    from kyno.store.sql import SqlConstitutionStore

    store = SqlConstitutionStore(url="sqlite://")
    store.create_all()
    cp = ControlPlane(store)
    cp.set_direction(mission="M1", change_note="init")
    reads = []
    real_head = store.head
    store.head = lambda name: reads.append(name) or real_head(name)

    head, delta = cp.head_and_delta(mission="M2")

    assert reads == ["default"]
    assert head == cp.current()
    assert delta == cp.preview_edit(mission="M2")


def test_given_an_empty_store_when_asking_head_and_delta_then_the_head_is_none():
    from kyno.service import ControlPlane
    from kyno.store.sql import SqlConstitutionStore

    store = SqlConstitutionStore(url="sqlite://")
    store.create_all()
    head, delta = ControlPlane(store).head_and_delta(mission="M1")
    assert head is None and delta == ("Creates 'default' at version 1.",)
