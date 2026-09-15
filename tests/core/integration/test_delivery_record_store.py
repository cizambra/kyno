"""Delivery records reference immutable direction and preserve request-specific deltas."""

import json
from copy import deepcopy
from datetime import UTC, datetime
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import event, func, inspect, select
from sqlalchemy.dialects import mysql
from sqlalchemy.exc import OperationalError
from sqlalchemy.schema import CreateTable

from kyno.service import ControlPlane
from kyno.store.delivery_record import SqlDeliveryRecordStore
from kyno.store.sql import SqlConstitutionStore


@pytest.fixture
def store():
    store = SqlConstitutionStore(url="sqlite://")
    store.create_all()
    return store


def append(store, direction, **kwargs):
    return SqlDeliveryRecordStore(store.engine).append(
        direction,
        operation=kwargs.pop("operation", "get_direction"),
        constitution=kwargs.pop("constitution", "missing"),
        arguments=kwargs.pop("arguments", {}),
        context=kwargs.pop("context", {"correlation_id": None, "metadata": {}}),
        **kwargs,
    )


def rows(store):
    with store.engine.connect() as connection:
        return (
            connection.execute(select(store.metadata.tables["kyno_delivery_records"]))
            .mappings()
            .all()
        )


def capture_statements(statements):
    def capture(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    return capture


def test_given_unknown_constitution_when_appending_twice_then_distinct_records_keep_version_zero(
    store,
):
    first = append(store, {"version": 0, "principles": []})
    second = append(store, {"version": 0, "principles": []})
    assert UUID(first) != UUID(second)
    records = rows(store)
    assert [record["record_id"] for record in records] == [first, second]
    assert [record["served_version"] for record in records] == [0, 0]
    assert all(record["constitution_id"] is None for record in records)
    assert all(datetime.fromisoformat(record["recorded_at"]).tzinfo == UTC for record in records)
    assert json.loads(records[0]["requester"]) is None
    with store.engine.connect() as connection:
        assert connection.execute(select(store.metadata.tables["kyno_constitutions"])).all() == []


def test_given_mutable_request_data_when_appending_then_delta_and_context_keep_original_values(
    store,
):
    direction = {"version": 0, "delta": ["Mission changed."]}
    context = {"correlation_id": "session", "metadata": {"nested": [1]}}
    requester = {"token_id": 2}
    arguments = {"known_version": 2, "detail": "full", "title": "Before"}
    expected_delta = deepcopy(direction["delta"])
    expected_context = deepcopy(context)
    expected_requester = deepcopy(requester)
    expected_selection = {"title": arguments["title"]}
    append(
        store,
        direction,
        context=context,
        requester=requester,
        arguments=arguments,
    )
    direction["delta"].append("Caller mutation")
    context["metadata"]["nested"].append(2)
    requester["token_id"] = 4
    record = rows(store)[0]
    assert json.loads(record["delta"]) == expected_delta
    assert json.loads(record["metadata"]) == expected_context["metadata"]
    assert json.loads(record["requester"]) == expected_requester
    assert json.loads(record["selection"]) == expected_selection
    assert (record["known_version"], record["detail_level"], record["correlation_id"]) == (
        arguments["known_version"],
        arguments["detail"],
        expected_context["correlation_id"],
    )


def test_given_get_changes_since_when_recording_then_current_version_becomes_served_version(
    store,
):
    plane = ControlPlane(store)
    for version in range(1, 8):
        plane.set_direction(
            constitution="missing", mission=f"Mission {version}", change_note="update"
        )
    append(store, {"current_version": 7}, operation="get_changes_since")
    assert rows(store)[0]["served_version"] == 7


def test_given_absent_table_when_appending_then_database_error_propagates(store):
    store.metadata.tables["kyno_delivery_records"].drop(store.engine)
    with pytest.raises(OperationalError):
        append(store, {"version": 0})


def test_given_non_json_delta_when_appending_then_no_partial_record_is_written(store):
    with pytest.raises(ValueError):
        append(store, {"version": 0, "delta": [float("nan")]})
    assert rows(store) == []


def test_given_custom_prefix_when_appending_then_only_prefixed_tables_are_used():
    store = SqlConstitutionStore(url="sqlite://", prefix="custom_")
    store.create_all()
    identifier = SqlDeliveryRecordStore(store.engine, prefix="custom_").append(
        {"version": 0},
        operation="get_direction",
        constitution="missing",
        arguments={},
        context={"correlation_id": None, "metadata": {}},
    )
    with store.engine.connect() as connection:
        assert (
            connection.scalar(select(store.metadata.tables["custom_delivery_records"].c.record_id))
            == identifier
        )
    assert all(name.startswith("custom_") for name in inspect(store.engine).get_table_names())
    record = SqlDeliveryRecordStore(store.engine, prefix="custom_").get(identifier)
    assert record["record_id"] == identifier
    assert record["served_version"] == 0
    assert record["delta"] is None


def test_given_mysql_schema_when_compiling_then_delta_supports_large_documents(
    store,
):
    statement = str(
        CreateTable(store.metadata.tables["kyno_delivery_records"]).compile(dialect=mysql.dialect())
    )
    assert "delta LONGTEXT NOT NULL" in statement


def test_given_unknown_record_id_when_getting_then_lookup_raises(store):
    append(store, {"version": 0})
    with pytest.raises(ValueError, match="^delivery record not found$"):
        SqlDeliveryRecordStore(store.engine).get("unknown")


@pytest.mark.parametrize("target_first", [True, False])
def test_given_multiple_deliveries_when_getting_by_id_then_exact_decoded_record_is_returned(
    store,
    target_first,
):
    direction = {"version": 0, "principles": [{"title": "Original"}]}
    if not target_first:
        append(store, {"version": 0, "principles": []})
    identifier = append(
        store,
        direction,
        requester={"token_id": 8},
        context={"correlation_id": "session", "metadata": {"nested": [1]}},
        arguments={"title": "Original"},
    )
    if target_first:
        append(store, {"version": 0, "principles": []})
    raw = next(record for record in rows(store) if record["record_id"] == identifier)
    expected = {
        "record_id": identifier,
        "recorded_at": raw["recorded_at"],
        "constitution_id": None,
        "requested_constitution": "missing",
        "served_version": 0,
        "operation": "get_direction",
        "known_version": None,
        "detail_level": None,
        "selection": {"title": "Original"},
        "delta": None,
        "requester": {"token_id": 8},
        "correlation_id": "session",
        "metadata": {"nested": [1]},
    }
    assert set(raw) == set(expected) | {"sequence"}
    assert SqlDeliveryRecordStore(store.engine).get(identifier) == expected


def test_given_updates_and_mutations_when_getting_delivery_then_version_and_delta_are_unchanged(
    store,
):
    plane = ControlPlane(store)
    plane.set_direction(constitution="missing", mission="Original", change_note="initial")
    direction = {"version": 1, "delta": ["Original delta"]}
    identifier = append(
        store, direction, context={"correlation_id": None, "metadata": {"nested": [1]}}
    )
    first = SqlDeliveryRecordStore(store.engine).get(identifier)
    first["delta"].append("Mutated")
    first["metadata"]["nested"].append(2)
    plane.set_direction(constitution="missing", mission="New mission", change_note="updated")
    restored = SqlDeliveryRecordStore(store.engine).get(identifier)
    assert restored["delta"] == ["Original delta"]
    assert store.get("missing", restored["served_version"]).mission == "Original"
    assert restored["metadata"] == {"nested": [1]}
    assert restored["requester"] is None
    assert restored["served_version"] == 1


def test_given_persisted_delivery_when_getting_then_only_select_is_executed(store):
    identifier = append(store, {"version": 0})
    statements = []
    capture = capture_statements(statements)
    event.listen(store.engine, "before_cursor_execute", capture)
    try:
        SqlDeliveryRecordStore(store.engine).get(identifier)
    finally:
        event.remove(store.engine, "before_cursor_execute", capture)
    assert len(statements) == 1
    assert statements[0].startswith("SELECT ")


def test_given_version_one_when_recording_its_delivery_then_constitution_history_is_unchanged(
    store,
):
    plane = ControlPlane(store)
    plane.set_direction(constitution="missing", mission="Original", change_note="initial")
    with store.engine.connect() as connection:
        before = connection.execute(
            select(store.metadata.tables["kyno_constitution_versions"])
        ).all()
        constitution_id = connection.scalar(
            select(store.metadata.tables["kyno_constitutions"].c.id)
        )
    append(store, {"version": 1, "mission": "Original"})
    assert rows(store)[0]["constitution_id"] == constitution_id
    with store.engine.connect() as connection:
        assert (
            connection.execute(select(store.metadata.tables["kyno_constitution_versions"])).all()
            == before
        )


def test_given_two_constitutions_when_recording_the_second_then_it_links_to_the_second(store):
    plane = ControlPlane(store)
    plane.set_direction(constitution="sales", mission="Grow revenue", change_note="initial")
    plane.set_direction(constitution="support", mission="Resolve issues", change_note="initial")
    constitutions = store.metadata.tables["kyno_constitutions"]
    with store.engine.connect() as connection:
        support_id = connection.scalar(
            select(constitutions.c.id).where(constitutions.c.name == "support")
        )

    append(store, {"version": 1, "mission": "Resolve issues"}, constitution="support")

    record = rows(store)[0]
    assert record["requested_constitution"] == "support"
    assert record["constitution_id"] == support_id


@pytest.mark.parametrize("correlation_id", [None, "", "workflow-42/research"])
def test_given_migrated_database_when_reopened_then_committed_recording_is_preserved(
    tmp_path, correlation_id
):
    url = f"sqlite:///{tmp_path / 'recordings.sqlite3'}"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    store = SqlConstitutionStore(url=url)
    direction = {"version": 0, "mission": "", "principles": []}
    try:
        identifier = append(
            store, direction, context={"correlation_id": correlation_id, "metadata": {}}
        )
    finally:
        store.engine.dispose()

    reopened = SqlConstitutionStore(url=url)
    try:
        records = rows(reopened)
        assert len(records) == 1
        assert records[0]["record_id"] == identifier
        assert records[0]["correlation_id"] == correlation_id
        assert json.loads(records[0]["delta"]) is None
        saved = SqlDeliveryRecordStore(reopened.engine).get(identifier)
        assert saved["record_id"] == identifier
        assert saved["correlation_id"] == correlation_id
        assert saved["delta"] is None
        assert saved["served_version"] == 0
    finally:
        reopened.engine.dispose()


def test_given_commit_failure_when_recording_then_insert_rolls_back_and_prior_record_is_unchanged(
    store,
):
    append(store, {"version": 0, "mission": "Earlier response"})
    previous_records = rows(store)
    recordings = store.metadata.tables["kyno_delivery_records"]

    def fail_before_commit(connection):
        assert connection.scalar(select(func.count()).select_from(recordings)) == 2
        raise RuntimeError("recording commit failed")

    event.listen(store.engine, "commit", fail_before_commit)
    try:
        with pytest.raises(RuntimeError, match="^recording commit failed$"):
            append(store, {"version": 0, "mission": "Uncommitted response"})
    finally:
        event.remove(store.engine, "commit", fail_before_commit)

    assert rows(store) == previous_records


def test_given_responses_sharing_a_correlation_id_when_recording_then_each_keeps_its_own_metadata(
    store,
):
    direction = {"version": 0, "mission": ""}
    identifiers = [
        append(
            store,
            direction,
            context={"correlation_id": "workflow-42", "metadata": {"step": step}},
        )
        for step in ("first", "second")
    ]

    records = rows(store)
    assert len(records) == 2
    assert identifiers[0] != identifiers[1]
    assert [record["record_id"] for record in records] == identifiers
    assert [record["correlation_id"] for record in records] == ["workflow-42", "workflow-42"]
    assert [json.loads(record["metadata"]) for record in records] == [
        {"step": "first"},
        {"step": "second"},
    ]
    assert all(record["served_version"] == 0 for record in records)


@pytest.mark.parametrize(
    "payload, expected",
    [({}, None), ({"delta": []}, []), ({"delta": ["Mission changed."]}, ["Mission changed."])],
)
def test_given_optional_response_delta_when_recording_then_absent_and_empty_remain_distinct(
    store, payload, expected
):
    identifier = append(store, {"version": 0, **payload})
    assert SqlDeliveryRecordStore(store.engine).get(identifier)["delta"] == expected


@pytest.mark.parametrize("constitution, version", [("missing", 1), ("existing", 2)])
def test_given_missing_constitution_or_version_when_recording_then_no_dangling_reference_is_saved(
    store, constitution, version
):
    ControlPlane(store).set_direction(
        constitution="existing", mission="Initial", change_note="initial"
    )
    with pytest.raises(ValueError, match="served constitution version not found"):
        append(store, {"version": version}, constitution=constitution)
    assert rows(store) == []
