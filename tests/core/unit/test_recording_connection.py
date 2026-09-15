from types import SimpleNamespace

import pytest
from sqlalchemy.engine import make_url

from kyno.store.recording_connection import _connect_args


def engine(url, dialect, driver):
    return SimpleNamespace(url=make_url(url), dialect=SimpleNamespace(name=dialect, driver=driver))


@pytest.mark.parametrize(
    "timeout, milliseconds, seconds, keepalive_seconds",
    [(0.00001, 1, 2, 1), (0.25, 250, 2, 1), (2.5, 2500, 3, 3)],
)
def test_given_postgres_when_configuring_recording_then_timeouts_round_up_to_driver_limits(
    timeout, milliseconds, seconds, keepalive_seconds
):
    source = engine(
        "postgresql+psycopg://localhost/kyno?options=-c%20search_path%3Dcustom",
        "postgresql",
        "psycopg",
    )
    options = _connect_args(source, timeout)
    assert options["connect_timeout"] == seconds
    assert options["options"] == f"-c search_path=custom -c statement_timeout={milliseconds}"
    assert options["tcp_user_timeout"] == milliseconds
    assert options["keepalives"] == options["keepalives_count"] == 1
    assert options["keepalives_idle"] == options["keepalives_interval"] == keepalive_seconds


@pytest.mark.parametrize("dialect", ["mysql", "mariadb"])
def test_given_mysql_timeout_when_configuring_connection_then_socket_reads_and_writes_have_limits(
    dialect,
):
    source = engine("mysql+pymysql://localhost/kyno", dialect, "pymysql")
    assert _connect_args(source, 0.25) == {
        "connect_timeout": 1,
        "read_timeout": 0.25,
        "write_timeout": 0.25,
    }


def test_given_unknown_driver_when_configuring_recording_then_unbounded_connection_is_refused():
    source = engine("postgresql+psycopg2://localhost/kyno", "postgresql", "psycopg2")
    with pytest.raises(ValueError, match="recording timeouts require"):
        _connect_args(source, 1)


def test_given_submillisecond_timeout_when_configuring_sqlite_then_lock_wait_limit_stays_enabled():
    source = engine("sqlite://", "sqlite", "pysqlite")
    assert _connect_args(source, 0.000001) == {"timeout": 0.001}


def test_given_large_timeout_when_configuring_postgres_then_native_limits_do_not_overflow():
    source = engine("postgresql+psycopg://localhost/kyno", "postgresql", "psycopg")
    options = _connect_args(source, 1e308)
    assert options["tcp_user_timeout"] == 2147483647
    assert options["connect_timeout"] == 31536000
