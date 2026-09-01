import os
import uuid

import pytest

from kyno.store.sql import SqlConstitutionStore

# Set this to point the "postgres" case of `store` at a real server, e.g.:
#   KYNO_TEST_POSTGRES_URL=postgresql+psycopg://user:pass@host/db pytest
POSTGRES_URL_ENV = "KYNO_TEST_POSTGRES_URL"
MYSQL_URL_ENV = "KYNO_TEST_MYSQL_URL"


def _postgres_url() -> str | None:
    return os.environ.get(POSTGRES_URL_ENV)


def _mysql_url() -> str | None:
    return os.environ.get(MYSQL_URL_ENV)


def _random_prefix() -> str:
    # Postgres identifiers top out at 63 bytes; this is well under that
    # even once "constitution_versions" and "uq_constitution_version" are
    # appended by build_metadata().
    return f"jt_{uuid.uuid4().hex[:12]}_"


needs_postgres = pytest.mark.skipif(
    not _postgres_url(),
    reason=f"set {POSTGRES_URL_ENV} to run the Postgres store suite",
)

needs_mysql = pytest.mark.skipif(
    not _mysql_url(),
    reason=f"set {MYSQL_URL_ENV} to run the MySQL store suite",
)


@pytest.fixture(
    params=[
        "sqlite",
        pytest.param("postgres", marks=needs_postgres),
        pytest.param("mysql", marks=needs_mysql),
    ]
)
def store(request, tmp_path):
    """A created SqlConstitutionStore, parametrized over both backends;
    postgres uses a randomly prefixed table pair per test so tests never
    see each other's rows on the shared server."""
    if request.param == "sqlite":
        url = f"sqlite:///{tmp_path / 'store.sqlite3'}"
        store = SqlConstitutionStore(url=url)
        store.create_all()
        yield store
    else:
        url = _postgres_url() if request.param == "postgres" else _mysql_url()
        store = SqlConstitutionStore(url=url, prefix=_random_prefix())
        store.create_all()
        try:
            yield store
        finally:
            store.metadata.drop_all(store.engine)
            store.engine.dispose()
