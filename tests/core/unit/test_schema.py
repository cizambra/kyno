from sqlalchemy import DateTime
from sqlalchemy.dialects import mysql

from kyno.store.schema import build_metadata


def test_given_mysql_when_building_metadata_then_timestamps_keep_six_fractional_digits():
    metadata, *_ = build_metadata()
    timestamps = [
        column
        for table in metadata.tables.values()
        for column in table.columns
        if isinstance(column.type, DateTime)
    ]
    assert timestamps
    for column in timestamps:
        assert column.type.compile(dialect=mysql.dialect()) == "DATETIME(6)", column
