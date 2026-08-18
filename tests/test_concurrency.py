import threading

from kyno.errors import VersionConflictError
from kyno.service import ControlPlane


def test_parallel_appends_serialize_by_unique_index(store):
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


def test_service_level_contention_through_control_plane(store):
    # Unlike the append()-level test above, this exercises ControlPlane's
    # retry loop itself, not just the unique-index guard -- hence the
    # generous max_retries (up to 7 of 8 threads may need to retry).
    cp = ControlPlane(store, max_retries=20)

    def writer(i):
        cp.set_direction(mission=f"M{i}", change_note=f"note{i}")

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    versions = sorted(v.version for v in store.versions_after("default", 0))
    assert versions == list(range(1, 9))
    assert store.head("default").version == 8


def test_concurrent_first_write_to_same_new_constitution_name_maps_to_conflict(store):
    # Deliberate: colliding on a brand-new name hits the name's unique constraint,
    # not the version one -- append() maps that IntegrityError to
    # VersionConflictError too, exactly like a version collision.
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
