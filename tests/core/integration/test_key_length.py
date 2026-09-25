"""Key length boundaries preserve stored identity and direction history."""

import pytest
from sqlalchemy import select

from kyno.service import ControlPlane
from kyno.store.delivery_record import SqlDeliveryRecordStore
from kyno.wire.constitution import InvalidConstitutionKeyError
from tests.stores import create_memory_store


@pytest.fixture
def ledger():
    source = create_memory_store()
    try:
        ControlPlane(source).apply_direction(mission="Imported", change_note="init")
        yield source.export_versions("default")
    finally:
        source.engine.dispose()


@pytest.mark.parametrize("operation", ["apply", "append", "import"])
@pytest.mark.parametrize("populated", [False, True])
@pytest.mark.parametrize("padding", ["", " \t"])
def test_given_overlong_key_when_writing_then_identity_and_version_tables_are_unchanged(
    memory_store, ledger, operation, populated, padding
):
    plane = ControlPlane(memory_store)
    prefix = "a" * 200
    if populated:
        plane.apply_direction(mission="Existing", change_note="init", constitution=prefix)
    tables = [
        memory_store.metadata.tables[name]
        for name in ("kyno_constitutions", "kyno_constitution_versions")
    ]
    with memory_store.engine.connect() as connection:
        before = [connection.execute(select(table).order_by(table.c.id)).all() for table in tables]

    key = f"{padding}{prefix}b{padding}"
    with pytest.raises(InvalidConstitutionKeyError, match="200"):
        if operation == "apply":
            plane.apply_direction(mission="New", change_note="update", constitution=key)
        elif operation == "append":
            memory_store.append(
                key,
                version=2 if populated else 1,
                mission="New",
                principles=(),
                change_note="update",
                changed_mission=True,
                changed_principles=False,
                created_by=None,
            )
        else:
            memory_store.import_versions(key, ledger)

    with memory_store.engine.connect() as connection:
        after = [connection.execute(select(table).order_by(table.c.id)).all() for table in tables]
    assert after == before


def test_given_200_character_key_when_filtering_delivery_history_then_exact_identity_is_selected(
    memory_store,
):
    history = SqlDeliveryRecordStore(memory_store.engine)
    key = "a" * 200
    identifiers = {}
    for name in (key, "other"):
        identifiers[name] = history.append(
            {"version": 0},
            operation="get_direction",
            constitution=name,
            arguments={},
            context={"correlation_id": None, "metadata": {}},
        )
    records = history.list(constitution=f" \t{key}\n")["items"]
    assert [record["record_id"] for record in records] == [identifiers[key]]


@pytest.mark.parametrize("padding", ["", " \t"])
def test_given_overlong_filter_when_listing_delivery_history_then_key_error_is_raised(
    memory_store, padding
):
    history = SqlDeliveryRecordStore(memory_store.engine)
    with pytest.raises(InvalidConstitutionKeyError, match="200"):
        history.list(constitution=f"{padding}{'a' * 201}{padding}")
