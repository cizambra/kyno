import threading

from kyno.errors import VersionConflictError
from kyno.service import ControlPlane


def test_given_parallel_appends_when_racing_for_a_version_then_the_unique_index_serializes_them(
    store,
):
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

    successes: list[int] = []
    conflicts: list[int] = []

    def writer():
        try:
            store.append(
                "default",
                2,
                mission="M2",
                principles=(),
                change_note="x",
                changed_mission=True,
                changed_principles=False,
                created_by=None,
            )
            successes.append(2)
        except VersionConflictError:
            conflicts.append(2)

    threads = [threading.Thread(target=writer) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(successes) == 1
    assert len(conflicts) == 7


def test_given_contending_writers_when_applying_then_conflicts_surface_and_nothing_is_lost(store):
    # Racing writers don't get silently merged: each either lands or is told
    # the head moved. The store never skips or reuses a version.
    cp = ControlPlane(store)
    landed: list[int] = []
    refused: list[int] = []

    def writer(i):
        try:
            landed.append(cp.set_direction(mission=f"M{i}", change_note=f"note{i}").version)
        except VersionConflictError:
            refused.append(i)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(landed) + len(refused) == 8
    versions = sorted(v.version for v in store.versions_after("default", 0))
    assert versions == list(range(1, len(landed) + 1))
    assert sorted(landed) == versions
    assert store.head("default").version == len(landed)


def test_given_concurrent_first_writes_to_a_new_name_when_racing_then_both_map_to_conflict(store):
    # Deliberate: colliding on a brand-new name hits the name's unique
    # constraint, not the version one. append() maps that IntegrityError to
    # VersionConflictError as well, the same as a version collision.
    successes: list[int] = []
    conflicts: list[int] = []

    def writer():
        try:
            store.append(
                "brand-new",
                1,
                mission="M",
                principles=(),
                change_note="init",
                changed_mission=True,
                changed_principles=True,
                created_by=None,
            )
            successes.append(1)
        except VersionConflictError:
            conflicts.append(1)

    threads = [threading.Thread(target=writer) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(successes) == 1
    assert len(conflicts) == 1
    assert store.head("brand-new").version == 1
