import pytest
from sqlalchemy import DateTime
from sqlalchemy.dialects import mysql, postgresql, sqlite

from kyno.store.schema import build_metadata


@pytest.mark.parametrize(
    "dialect, expected",
    [
        (mysql.dialect(), "DATETIME(6)"),
        (postgresql.dialect(), "TIMESTAMP WITH TIME ZONE"),
        (sqlite.dialect(), "DATETIME"),
    ],
)
def test_given_a_database_dialect_when_building_metadata_then_timestamps_use_its_storage_type(
    dialect, expected
):
    metadata, *_ = build_metadata()
    timestamps = [
        column
        for table in metadata.tables.values()
        for column in table.columns
        if isinstance(column.type, DateTime)
    ]
    assert timestamps
    for column in timestamps:
        assert column.type.compile(dialect=dialect) == expected, column
