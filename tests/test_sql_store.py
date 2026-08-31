import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, delete

from kyno.errors import CorruptStateError, VersionConflictError
from kyno.models import Principle
from kyno.service import ControlPlane
from kyno.store.sql import SqlConstitutionStore

# The `store` fixture (sqlite + postgres, see tests/conftest.py) is injected
# by pytest -- no local definition needed here.


def test_given_an_append_when_reading_head_then_it_is_the_appended_version(store):
    v1 = store.append(
        "default",
        1,
        mission="M1",
        principles=("p1",),
        change_note="init",
        changed_mission=True,
        changed_principles=True,
        created_by="op",
    )
    assert v1.version == 1
    head = store.head("default")
    assert head.version == 1 and head.mission == "M1"
    assert head.principles == (Principle("p1"),)


def test_given_an_append_when_reading_head_then_created_at_is_tz_aware_and_matches(store):
    # SQLite drops tzinfo on read even for a DateTime(timezone=True) column;
    # append()'s and head()'s values must still agree on being tz-aware UTC.
    v1 = store.append(
        "default",
        1,
        mission="M1",
        principles=("p1",),
        change_note="init",
        changed_mission=True,
        changed_principles=True,
        created_by=None,
    )
    head = store.head("default")
    assert v1.created_at.tzinfo is not None
    assert head.created_at.tzinfo is not None
    assert head.created_at == v1.created_at


def test_given_an_unknown_name_when_reading_head_then_it_is_none(store):
    assert store.head("nope") is None


def test_given_several_versions_when_reading_versions_after_then_they_are_ordered(store):
    store.append(
        "default",
        1,
        mission="M1",
        principles=("p1",),
        change_note="a",
        changed_mission=True,
        changed_principles=True,
        created_by=None,
    )
    store.append(
        "default",
        2,
        mission="M2",
        principles=("p1",),
        change_note="b",
        changed_mission=True,
        changed_principles=False,
        created_by=None,
    )
    store.append(
        "default",
        3,
        mission="M2",
        principles=("p1", "p2"),
        change_note="c",
        changed_mission=False,
        changed_principles=True,
        created_by=None,
    )
    after = store.versions_after("default", 1)
    assert [v.version for v in after] == [2, 3]
    assert after[-1].change_note == "c"


def test_given_a_taken_version_number_when_appending_then_a_conflict_raises(store):
    store.append(
        "default",
        1,
        mission="M",
        principles=(),
        change_note="x",
        changed_mission=True,
        changed_principles=True,
        created_by=None,
    )
    with pytest.raises(VersionConflictError):
        store.append(
            "default",
            1,
            mission="M",
            principles=(),
            change_note="x",
            changed_mission=True,
            changed_principles=True,
            created_by=None,
        )


def test_given_principles_when_writing_and_reading_then_they_round_trip_as_json(store):
    store.append(
        "default",
        1,
        mission="M",
        principles=("a, b", 'q"x'),
        change_note="x",
        changed_mission=True,
        changed_principles=True,
        created_by=None,
    )
    assert store.head("default").principles == (Principle("a, b"), Principle('q"x'))


def test_given_a_missing_pointed_version_row_when_reading_head_then_corrupt_state_raises(store):
    store.append(
        "default",
        1,
        mission="M1",
        principles=("p1",),
        change_note="init",
        changed_mission=True,
        changed_principles=True,
        created_by="op",
    )
    # Simulates corruption: a dangling current_version pointer with no matching version row.
    with store.engine.begin() as conn:
        conn.execute(delete(store._versions).where(store._versions.c.version == 1))
    with pytest.raises(CorruptStateError):
        store.head("default")


def test_given_both_an_engine_and_a_url_when_building_the_store_then_it_is_refused():
    with pytest.raises(ValueError):
        SqlConstitutionStore()


def test_given_the_control_plane_when_writing_then_the_ledger_is_append_only(store):
    cp = ControlPlane(store)
    cp.set_direction(mission="M1", principles=("p1",), change_note="init")
    cp.set_direction(mission="M2", change_note="pivot")
    cp.set_direction(principles=("p1", "p2"), change_note="add p2")

    v1 = store.get("default", 1)
    assert v1.mission == "M1"
    assert v1.principles == (Principle("p1"),)
    assert v1.change_note == "init"

    all_versions = store.versions_after("default", 0)
    assert len(all_versions) == 3


def test_given_an_injected_engine_when_using_the_store_then_it_works_end_to_end(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'injected.sqlite3'}", connect_args={"check_same_thread": False}
    )
    store = SqlConstitutionStore(engine=engine)
    store.create_all()
    v = store.append(
        "default",
        1,
        mission="M1",
        principles=("p1",),
        change_note="init",
        changed_mission=True,
        changed_principles=True,
        created_by=None,
    )
    head = store.head("default")
    assert head.version == v.version == 1
    assert head.mission == "M1" and head.principles == (Principle("p1"),)


def test_given_a_losing_append_when_the_conflict_raises_then_the_head_is_intact(store):
    # A stale-version append must roll back the whole transaction -- both the
    # failed insert AND the current_version update that ran earlier in it.
    store.append(
        "default",
        1,
        mission="M1",
        principles=(),
        change_note="a",
        changed_mission=True,
        changed_principles=True,
        created_by=None,
    )
    store.append(
        "default",
        2,
        mission="M2",
        principles=(),
        change_note="b",
        changed_mission=True,
        changed_principles=False,
        created_by=None,
    )
    store.append(
        "default",
        3,
        mission="M3",
        principles=(),
        change_note="c",
        changed_mission=True,
        changed_principles=False,
        created_by=None,
    )

    with pytest.raises(VersionConflictError):
        store.append(
            "default",
            2,
            mission="stale",
            principles=(),
            change_note="stale",
            changed_mission=True,
            changed_principles=True,
            created_by=None,
        )

    head = store.head("default")
    assert head.version == 3
    assert head.mission == "M3"


def test_given_two_names_when_appending_to_each_then_their_version_sequences_stay_separate(store):
    store.append(
        "default",
        1,
        mission="M",
        principles=(),
        change_note="a",
        changed_mission=True,
        changed_principles=True,
        created_by=None,
    )
    store.append(
        "other",
        1,
        mission="N",
        principles=(),
        change_note="b",
        changed_mission=True,
        changed_principles=True,
        created_by=None,
    )
    store.append(
        "default",
        2,
        mission="M2",
        principles=(),
        change_note="c",
        changed_mission=True,
        changed_principles=False,
        created_by=None,
    )

    assert store.head("default").version == 2
    assert store.head("other").version == 1


def test_given_an_empty_store_when_exporting_versions_then_the_list_is_empty(store):
    # Consistent with the read-never-fails contract: empty yields [], not an error.
    assert store.export_versions() == []


def test_given_a_full_range_when_exporting_versions_then_plain_dicts_come_back_ascending(store):
    cp = ControlPlane(store)
    cp.set_direction(mission="M1", principles=("p1",), change_note="init", created_by="alice")
    cp.set_direction(mission="M2", change_note="pivot", created_by="bob")
    cp.set_direction(principles=("p1", "p2"), change_note="add p2", created_by="alice")

    rows = store.export_versions()

    assert [r["version"] for r in rows] == [1, 2, 3]
    assert rows[0] == {
        "version": 1,
        "mission": "M1",
        "declaration": "",
        "principles": [{"title": "p1", "description": ""}],
        "change_note": "init",
        "created_by": "alice",
        "authorized_by": None,
        "created_at": rows[0]["created_at"],
    }
    assert rows[1]["mission"] == "M2" and rows[1]["created_by"] == "bob"
    assert [p["title"] for p in rows[2]["principles"]] == ["p1", "p2"]
    from datetime import datetime

    parsed = datetime.fromisoformat(rows[0]["created_at"])
    assert parsed.tzinfo is not None


def test_given_range_bounds_when_exporting_versions_then_they_are_inclusive(store):
    cp = ControlPlane(store)
    cp.set_direction(mission="M1", change_note="v1")
    cp.set_direction(mission="M2", change_note="v2")
    cp.set_direction(mission="M3", change_note="v3")

    assert [r["version"] for r in store.export_versions(from_version=2)] == [2, 3]
    assert [r["version"] for r in store.export_versions(to_version=2)] == [1, 2]
    assert [r["version"] for r in store.export_versions(from_version=2, to_version=2)] == [2]


def test_given_out_of_range_bounds_when_exporting_versions_then_the_list_is_empty(store):
    cp = ControlPlane(store)
    cp.set_direction(mission="M1", change_note="v1")

    assert store.export_versions(from_version=5) == []


def test_given_a_name_when_exporting_versions_then_only_that_constitution_exports(store):
    store.append(
        "default",
        1,
        mission="M",
        principles=(),
        change_note="a",
        changed_mission=True,
        changed_principles=True,
        created_by=None,
    )
    store.append(
        "other",
        1,
        mission="N",
        principles=(),
        change_note="b",
        changed_mission=True,
        changed_principles=True,
        created_by=None,
    )

    rows = store.export_versions(constitution="other")
    assert len(rows) == 1 and rows[0]["mission"] == "N"


def test_given_an_in_memory_store_when_threads_share_it_then_they_see_one_database():
    import threading

    store = SqlConstitutionStore(url="sqlite://")
    store.create_all()
    store.append(
        "default",
        1,
        mission="M",
        principles=(),
        change_note="init",
        changed_mission=True,
        changed_principles=True,
        created_by=None,
    )

    seen = {}

    def reader():
        seen["v"] = store.head("default")

    t = threading.Thread(target=reader)
    t.start()
    t.join()
    assert seen["v"] is not None and seen["v"].version == 1


def _write(store, constitution="default", mission="M1"):
    return store.append(
        constitution,
        1,
        mission=mission,
        principles=("p1",),
        change_note="init",
        changed_mission=True,
        changed_principles=True,
        created_by=None,
    )


def test_given_a_written_constitution_when_reading_publication_then_it_starts_unpublished(store):
    _write(store)
    pub = store.publication("default")
    assert pub.published is False
    assert pub.published_at is None
    assert pub.history_public is False


def test_given_a_name_never_written_when_reading_publication_then_it_reads_as_private(store):
    # Reads never fail on an absent name elsewhere in this store; publication
    # follows the same rule -- "not published" is the honest answer.
    pub = store.publication("never-written")
    assert pub.published is False and pub.history_public is False


def test_given_set_publication_when_publishing_then_the_stamp_and_history_flag_are_recorded(store):
    _write(store)
    when = datetime(2026, 8, 12, 9, 30, tzinfo=UTC)
    assert store.set_publication("default", published_at=when, history_public=True) is True
    pub = store.publication("default")
    assert pub.published is True
    assert pub.published_at == when
    assert pub.history_public is True


def test_given_a_published_name_when_clearing_publication_then_it_is_private_again(store):
    _write(store)
    store.set_publication("default", published_at=datetime.now(UTC), history_public=True)
    store.set_publication("default", published_at=None, history_public=False)
    pub = store.publication("default")
    assert pub.published is False and pub.history_public is False


def test_given_a_name_that_does_not_exist_when_setting_publication_then_it_is_reported(store):
    assert store.set_publication("ghost", published_at=datetime.now(UTC), history_public=False) is (
        False
    )
    assert store.publication("ghost").published is False


def test_given_two_names_when_publishing_one_then_the_other_stays_private(store):
    # One Kyno holding an internal constitution and a public one: publishing
    # the public one must leave the internal one invisible.
    _write(store, "internal", "Internal mission")
    _write(store, "product", "Product mission")
    store.set_publication("product", published_at=datetime.now(UTC), history_public=True)

    assert store.publication("product").published is True
    assert store.publication("internal").published is False
    assert store.publication("internal").history_public is False


def test_given_several_names_when_publishing_each_then_history_settings_stay_per_name(store):
    _write(store, "a")
    _write(store, "b")
    store.set_publication("a", published_at=datetime.now(UTC), history_public=True)
    store.set_publication("b", published_at=datetime.now(UTC), history_public=False)

    assert store.publication("a").published and store.publication("a").history_public
    assert store.publication("b").published and not store.publication("b").history_public


def test_given_a_published_name_when_appending_a_version_then_publication_is_untouched(store):
    _write(store)
    when = datetime(2026, 8, 12, 9, 30, tzinfo=UTC)
    store.set_publication("default", published_at=when, history_public=True)
    store.append(
        "default",
        2,
        mission="M2",
        principles=("p1",),
        change_note="pivot",
        changed_mission=True,
        changed_principles=False,
        created_by=None,
    )
    pub = store.publication("default")
    assert pub.published_at == when and pub.history_public is True


# --- principles carry a title and an optional description ------------------


def _raw_principles(store, version=1, constitution="default"):
    """The JSON text actually written to the column."""
    from sqlalchemy import select

    with store.engine.connect() as conn:
        cid = store._constitution_id(conn, constitution)
        return conn.execute(
            select(store._versions.c.principles)
            .where(store._versions.c.constitution_id == cid)
            .where(store._versions.c.version == version)
        ).scalar_one()


def test_given_a_described_principle_when_writing_and_reading_then_it_survives(store):
    store.append(
        "default",
        1,
        mission="M",
        principles=(Principle("Be honest", "Say the hard number before the soft story."),),
        change_note="x",
        changed_mission=True,
        changed_principles=True,
        created_by=None,
    )
    assert store.head("default").principles == (
        Principle("Be honest", "Say the hard number before the soft story."),
    )


def test_given_a_title_only_principle_when_writing_then_it_is_stored_as_a_plain_json_string(store):
    # Deliberate: the column holds either shape, and a constitution nobody has
    # described writes exactly the JSON it always did -- so adopting
    # descriptions is what changes the stored bytes, not upgrading.
    store.append(
        "default",
        1,
        mission="M",
        principles=(Principle("p1"), Principle("p2", "why p2")),
        change_note="x",
        changed_mission=True,
        changed_principles=True,
        created_by=None,
    )
    assert json.loads(_raw_principles(store)) == [
        "p1",
        {"title": "p2", "description": "why p2"},
    ]


def test_given_a_row_of_plain_strings_when_reading_then_they_are_title_only_principles(store):
    # The shape every version written before descriptions existed is in.
    store.append(
        "default",
        1,
        mission="M",
        principles=("p1", "p2"),
        change_note="x",
        changed_mission=True,
        changed_principles=True,
        created_by=None,
    )
    assert store.head("default").principles == (Principle("p1"), Principle("p2"))


def test_given_described_principles_when_exporting_then_each_description_is_carried(store):
    ControlPlane(store).set_direction(
        mission="M1",
        principles=("p1", {"title": "p2", "description": "why p2"}),
        change_note="init",
    )
    assert store.export_versions()[0]["principles"] == [
        {"title": "p1", "description": ""},
        {"title": "p2", "description": "why p2"},
    ]


# --- the declaration -------------------------------------------------------


def test_given_a_declaration_when_writing_and_reading_then_it_survives(store):
    store.append(
        "default",
        1,
        mission="M",
        principles=(),
        declaration="# Our declaration\n\nThe long form.",
        change_note="x",
        changed_mission=True,
        changed_principles=True,
        created_by=None,
    )
    assert store.head("default").declaration == "# Our declaration\n\nThe long form."


def test_given_a_version_without_a_declaration_when_reading_then_it_is_an_empty_one(store):
    # The column is nullable, so "never written" and "" answer the same way
    # rather than handing callers a None to guard against.
    store.append(
        "default",
        1,
        mission="M",
        principles=(),
        change_note="x",
        changed_mission=True,
        changed_principles=True,
        created_by=None,
    )
    assert store.head("default").declaration == ""


def test_given_a_declaration_when_exporting_then_it_is_carried(store):
    ControlPlane(store).set_direction(
        mission="M1", declaration="The long form.", change_note="init"
    )
    assert store.export_versions()[0]["declaration"] == "The long form."


def test_given_an_unwritten_name_when_getting_one_version_then_it_is_none(store):
    assert store.get("nope", 1) is None


def test_given_an_existing_constitution_when_getting_a_version_never_reached_then_it_is_none(store):
    store.append(
        "default",
        1,
        mission="M",
        principles=(),
        change_note="n",
        changed_mission=True,
        changed_principles=False,
        created_by=None,
    )
    assert store.get("default", 9) is None


def test_given_an_unwritten_name_when_pulling_versions_after_zero_then_nothing_comes_back(store):
    assert store.versions_after("nope", 0) == []


def test_given_an_authorization_when_appending_then_it_round_trips(store):
    store.append(
        "default",
        1,
        mission="M",
        principles=(),
        change_note="n",
        changed_mission=True,
        changed_principles=False,
        created_by="ci",
        authorized_by="automation",
    )
    assert store.head("default").authorized_by == "automation"
    assert store.export_versions("default")[0]["authorized_by"] == "automation"


def test_given_no_authorization_when_appending_then_none_is_stored(store):
    store.append(
        "default",
        1,
        mission="M",
        principles=(),
        change_note="n",
        changed_mission=True,
        changed_principles=False,
        created_by=None,
    )
    assert store.head("default").authorized_by is None
