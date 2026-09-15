"""Delivery history queries filter and bound persisted delivery records."""

import json

import pytest
from sqlalchemy import insert, update

from kyno.store.delivery_record import SqlDeliveryRecordStore
from kyno.store.sql import SqlConstitutionStore


@pytest.fixture
def history():
    store = SqlConstitutionStore(url="sqlite://")
    store.create_all()
    with store.engine.begin() as connection:
        for index, (correlation_id, constitution) in enumerate(
            [("one", "alpha"), ("two", "alpha"), ("one", "beta"), ("", "alpha")], start=1
        ):
            connection.execute(
                insert(store.metadata.tables["kyno_delivery_records"]).values(
                    record_id=str(index),
                    recorded_at=f"2026-01-01T0{index}:00:00.000000+00:00",
                    requested_constitution=constitution,
                    served_version=0,
                    operation="get_direction",
                    selection=json.dumps({"title": "Example"}),
                    delta="null",
                    requester="null",
                    correlation_id=correlation_id,
                    metadata=json.dumps({"nested": [index]}),
                )
            )
    yield SqlDeliveryRecordStore(store.engine)
    store.engine.dispose()


@pytest.mark.parametrize(
    "filters, expected",
    [
        ({}, ["1", "2", "3", "4"]),
        ({"correlation_id": "one"}, ["1", "3"]),
        ({"constitution": "alpha"}, ["1", "2", "4"]),
        ({"correlation_id": "one", "constitution": "beta"}, ["3"]),
        ({"correlation_id": ""}, ["4"]),
        ({"constitution": "absent"}, []),
        ({"correlation_id": "absent"}, []),
        ({"correlation_id": "one", "constitution": "beta", "limit": 1}, ["3"]),
        ({"since": "2026-01-01T03:00:00Z", "limit": 1}, ["3"]),
        ({"correlation_id": "one", "until": "2026-01-01T02:00:00Z"}, ["1"]),
        ({"since": "2026-01-01T02:00:00Z"}, ["2", "3", "4"]),
        ({"until": "2026-01-01T02:00:00Z"}, ["1", "2"]),
        ({"since": "2026-01-01T03:00:00+01:00", "until": "2025-12-31T21:00:00-05:00"}, ["2"]),
        (
            {
                "correlation_id": "one",
                "constitution": "beta",
                "since": "2026-01-01T02:00:00Z",
                "until": "2026-01-01T04:00:00Z",
            },
            ["3"],
        ),
    ],
)
def test_given_history_when_filtering_then_matching_records_are_oldest_first(
    history, filters, expected
):
    assert [record["record_id"] for record in history.list(**filters)] == expected


def test_given_stored_json_when_listing_then_values_are_decoded_without_sequence(history):
    record = history.list(limit=1)[0]
    assert record["delta"] is None
    assert record["selection"] == {"title": "Example"}
    assert record["requester"] is None
    assert record["metadata"] == {"nested": [1]}
    assert "sequence" not in record
    record["metadata"]["nested"].append(2)
    assert history.list(limit=1)[0]["metadata"] == {"nested": [1]}


@pytest.mark.parametrize("limit", [1, 2, 100])
def test_given_valid_limit_when_listing_then_results_are_bounded(history, limit):
    assert len(history.list(limit=limit)) == min(limit, 4)


@pytest.mark.parametrize("limit", [0, -1, 101, True, 1.5, "2", None])
def test_given_invalid_limit_when_listing_then_it_is_rejected(history, limit):
    with pytest.raises(ValueError, match="limit must be an integer from 1 to 100"):
        history.list(limit=limit)


@pytest.mark.parametrize("bound", ["since", "until"])
@pytest.mark.parametrize("value", ["bad", "", "2026-01-01", "2026-01-01T00:00:00", 123])
def test_given_invalid_timestamp_when_listing_then_it_is_rejected(history, bound, value):
    with pytest.raises(ValueError, match="history timestamps must"):
        history.list(**{bound: value})


def test_given_reversed_time_bounds_when_listing_then_the_range_is_rejected(history):
    with pytest.raises(ValueError, match="since must not be later than until"):
        history.list(since="2026-01-01T05:00:00Z", until="2026-01-01T04:00:00Z")


@pytest.mark.parametrize(
    "arguments, expected_count", [({}, 50), ({"limit": 1}, 1), ({"limit": 100}, 100)]
)
def test_given_more_than_one_hundred_records_when_listing_then_the_page_limit_is_applied(
    history, arguments, expected_count
):
    for _index in range(101):
        history.append(
            {"version": 0},
            operation="get_direction",
            constitution="extra",
            arguments={},
            context={"correlation_id": None, "metadata": {}},
        )
    assert len(history.list(**arguments)) == expected_count


def test_given_timestamps_out_of_insertion_order_when_listing_then_insertion_order_is_preserved(
    history,
):
    with history._engine.begin() as connection:
        connection.execute(
            update(history._table)
            .where(history._table.c.record_id == "1")
            .values(recorded_at="2026-01-02T00:00:00.000000+00:00")
        )
    assert [record["record_id"] for record in history.list()] == ["1", "2", "3", "4"]
