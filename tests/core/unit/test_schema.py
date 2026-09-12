from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateTable

from kyno.store.schema import build_metadata


def test_given_mysql_when_building_delivery_schema_then_full_direction_has_large_text_capacity():
    metadata, *_ = build_metadata()
    definition = str(
        CreateTable(metadata.tables["kyno_deliveries"]).compile(dialect=mysql.dialect())
    )
    assert "direction LONGTEXT" in definition
