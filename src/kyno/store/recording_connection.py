"""Recording-only connections with database and driver wait limits."""

from contextlib import contextmanager
from math import ceil

from sqlalchemy import URL, Engine, create_engine, make_url
from sqlalchemy.pool import NullPool

from kyno.delivery import DeliverySettings

_MAX_TIMEOUT_MILLISECONDS = 2_147_483_647
_MAX_CONNECT_TIMEOUT_SECONDS = 31_536_000


def _milliseconds(timeout_seconds: float) -> int:
    return max(1, ceil(min(timeout_seconds, _MAX_TIMEOUT_MILLISECONDS / 1000) * 1000))


def _whole_seconds(timeout_seconds: float) -> int:
    return max(1, ceil(min(timeout_seconds, _MAX_CONNECT_TIMEOUT_SECONDS)))


def _connect_args(engine: Engine, timeout_seconds: float) -> dict:
    milliseconds = _milliseconds(timeout_seconds)
    seconds = _whole_seconds(timeout_seconds)
    dialect = engine.dialect.name
    if dialect == "sqlite":
        return {"timeout": milliseconds / 1000}
    if dialect == "postgresql" and engine.dialect.driver == "psycopg":
        options = engine.url.query.get("options", "")
        return {
            "connect_timeout": max(2, seconds),
            "options": f"{options} -c statement_timeout={milliseconds}",
            "keepalives": 1,
            "keepalives_idle": seconds,
            "keepalives_interval": seconds,
            "keepalives_count": 1,
            "tcp_user_timeout": milliseconds,
        }
    if dialect in ("mysql", "mariadb") and engine.dialect.driver == "pymysql":
        return {
            "connect_timeout": seconds,
            "read_timeout": min(timeout_seconds, _MAX_CONNECT_TIMEOUT_SECONDS),
            "write_timeout": min(timeout_seconds, _MAX_CONNECT_TIMEOUT_SECONDS),
        }
    raise ValueError("recording timeouts require SQLite, PostgreSQL/psycopg, or MySQL/PyMySQL")


@contextmanager
def _memory_transaction(engine: Engine, timeout_seconds: float):
    with engine.connect() as connection:
        raw = connection.connection.dbapi_connection
        cursor = raw.cursor()
        try:
            previous = cursor.execute("PRAGMA busy_timeout").fetchone()[0]
            milliseconds = _milliseconds(timeout_seconds)
            cursor.execute(f"PRAGMA busy_timeout = {milliseconds}")
            try:
                with connection.begin():
                    yield connection
            finally:
                cursor.execute(f"PRAGMA busy_timeout = {previous}")
        finally:
            cursor.close()


@contextmanager
def recording_transaction(
    engine: Engine, timeout_seconds: float, *, database_url: str | URL | None = None
):
    """Commit on success and roll back on failure, with recording-specific waits.

    File/server databases require an explicit URL for an unpooled connection.
    In-memory SQLite retains its existing connection so its data remains available.
    Limits apply to database operations, not total request duration.
    """
    DeliverySettings(recording_timeout_seconds=timeout_seconds)
    if database_url is not None and make_url(database_url) != engine.url:
        raise ValueError("recording database URL must match the direction engine URL")
    if engine.dialect.name == "sqlite" and (
        engine.url.database in (None, "", ":memory:")
        or engine.url.query.get("mode") == "memory"
        or (engine.url.database or "").startswith("file::memory:")
    ):
        with _memory_transaction(engine, timeout_seconds) as connection:
            yield connection
        return
    if database_url is None:
        raise ValueError("an explicit recording database URL is required for file/server databases")
    recording_engine = create_engine(
        database_url, poolclass=NullPool, connect_args=_connect_args(engine, timeout_seconds)
    )
    try:
        with recording_engine.begin() as connection:
            if engine.dialect.name in ("mysql", "mariadb"):
                seconds = _whole_seconds(timeout_seconds)
                connection.exec_driver_sql(
                    f"SET SESSION innodb_lock_wait_timeout={seconds}, "
                    f"SESSION lock_wait_timeout={seconds}"
                )
            yield connection
    finally:
        recording_engine.dispose()
