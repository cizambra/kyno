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


def test_append_then_head(store):
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


def test_head_created_at_is_tz_aware_and_matches_append(store):
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


def test_head_none_for_unknown(store):
    assert store.head("nope") is None


def test_versions_after_is_ordered(store):
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


def test_duplicate_version_raises_conflict(store):
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


def test_principles_roundtrip_json(store):
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


def test_head_raises_corrupt_state_when_pointed_version_row_missing(store):
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


def test_engine_or_url_but_not_both():
    with pytest.raises(ValueError):
        SqlConstitutionStore()


def test_append_only_immutability_via_control_plane(store):
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


def test_injectable_engine_happy_path(tmp_path):
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


def test_losing_append_leaves_head_intact(store):
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


def test_independent_constitution_names_keep_separate_version_sequences(store):
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


def test_export_versions_on_empty_store_returns_empty_list(store):
    # Consistent with the read-never-fails contract: empty yields [], not an error.
    assert store.export_versions() == []


def test_export_versions_full_range_returns_plain_dicts_in_ascending_order(store):
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
        "created_at": rows[0]["created_at"],
    }
    assert rows[1]["mission"] == "M2" and rows[1]["created_by"] == "bob"
    assert [p["title"] for p in rows[2]["principles"]] == ["p1", "p2"]
    from datetime import datetime

    parsed = datetime.fromisoformat(rows[0]["created_at"])
    assert parsed.tzinfo is not None


def test_export_versions_bounds_are_inclusive(store):
    cp = ControlPlane(store)
    cp.set_direction(mission="M1", change_note="v1")
    cp.set_direction(mission="M2", change_note="v2")
    cp.set_direction(mission="M3", change_note="v3")

    assert [r["version"] for r in store.export_versions(from_version=2)] == [2, 3]
    assert [r["version"] for r in store.export_versions(to_version=2)] == [1, 2]
    assert [r["version"] for r in store.export_versions(from_version=2, to_version=2)] == [2]


def test_export_versions_out_of_range_bounds_return_empty_list(store):
    cp = ControlPlane(store)
    cp.set_direction(mission="M1", change_note="v1")

    assert store.export_versions(from_version=5) == []


def test_export_versions_scoped_to_constitution_name(store):
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


def test_in_memory_store_is_shared_across_threads():
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


def test_a_written_constitution_starts_unpublished(store):
    _write(store)
    pub = store.publication("default")
    assert pub.published is False
    assert pub.published_at is None
    assert pub.history_public is False


def test_publication_of_a_name_never_written_reads_as_private(store):
    # Reads never fail on an absent name elsewhere in this store; publication
    # follows the same rule -- "not published" is the honest answer.
    pub = store.publication("never-written")
    assert pub.published is False and pub.history_public is False


def test_set_publication_records_the_stamp_and_the_history_flag(store):
    _write(store)
    when = datetime(2026, 8, 12, 9, 30, tzinfo=UTC)
    assert store.set_publication("default", published_at=when, history_public=True) is True
    pub = store.publication("default")
    assert pub.published is True
    assert pub.published_at == when
    assert pub.history_public is True


def test_set_publication_can_clear_back_to_private(store):
    _write(store)
    store.set_publication("default", published_at=datetime.now(UTC), history_public=True)
    store.set_publication("default", published_at=None, history_public=False)
    pub = store.publication("default")
    assert pub.published is False and pub.history_public is False


def test_set_publication_reports_a_name_that_does_not_exist(store):
    assert store.set_publication("ghost", published_at=datetime.now(UTC), history_public=False) is (
        False
    )
    assert store.publication("ghost").published is False


def test_publication_state_is_per_name(store):
    # One Kyno holding an internal constitution and a public one: publishing
    # the public one must leave the internal one invisible.
    _write(store, "internal", "Internal mission")
    _write(store, "product", "Product mission")
    store.set_publication("product", published_at=datetime.now(UTC), history_public=True)

    assert store.publication("product").published is True
    assert store.publication("internal").published is False
    assert store.publication("internal").history_public is False


def test_several_names_can_be_published_with_different_history_settings(store):
    _write(store, "a")
    _write(store, "b")
    store.set_publication("a", published_at=datetime.now(UTC), history_public=True)
    store.set_publication("b", published_at=datetime.now(UTC), history_public=False)

    assert store.publication("a").published and store.publication("a").history_public
    assert store.publication("b").published and not store.publication("b").history_public


def test_appending_a_version_leaves_publication_state_alone(store):
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


def test_a_described_principle_survives_the_store(store):
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


def test_a_title_only_principle_is_written_as_a_plain_json_string(store):
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


def test_a_row_of_plain_strings_reads_back_as_title_only_principles(store):
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


def test_export_carries_each_principles_description(store):
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


def test_a_declaration_survives_the_store(store):
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


def test_a_version_written_without_a_declaration_reads_as_an_empty_one(store):
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


def test_export_carries_the_declaration(store):
    ControlPlane(store).set_direction(
        mission="M1", declaration="The long form.", change_note="init"
    )
    assert store.export_versions()[0]["declaration"] == "The long form."
