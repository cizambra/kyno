"""Asserts the deliberate choices behind the parametrized `store` fixture
in conftest.py -- the env var name, the skip reason, and the postgres
table-prefix generator.
"""

import re
from pathlib import Path

from tests.conftest import POSTGRES_URL_ENV, _postgres_url, _random_prefix, needs_postgres


def test_postgres_env_var_name_is_exact(monkeypatch):
    # This name is the documented way to opt into the Postgres tests; a typo
    # here would silently gate them on a variable nobody sets, so they would
    # skip forever without anyone noticing.
    assert POSTGRES_URL_ENV == "KYNO_TEST_POSTGRES_URL"
    monkeypatch.delenv(POSTGRES_URL_ENV, raising=False)
    assert _postgres_url() is None
    monkeypatch.setenv(POSTGRES_URL_ENV, "postgresql+psycopg://x/y")
    assert _postgres_url() == "postgresql+psycopg://x/y"


def test_skip_reason_names_the_env_var():
    reason = needs_postgres.kwargs["reason"]
    assert POSTGRES_URL_ENV in reason


def test_random_prefix_is_unique_safe_and_short_enough_for_postgres():
    a, b = _random_prefix(), _random_prefix()
    assert a != b
    for p in (a, b):
        assert re.fullmatch(r"[a-z][a-z0-9_]*", p)
        # Headroom for the longest suffix build_metadata() appends, still under the 63-byte cap.
        assert len(p) + len("uq_constitution_version") <= 63


def test_dev_extra_provides_psycopg_for_the_postgres_tests():
    # The Postgres tests need psycopg, and the dev extra is where it comes
    # from -- dropping it would turn them into a permanent skip.
    pyproject = Path(__file__).parent.parent / "pyproject.toml"
    text = pyproject.read_text()
    dev_extra = text.split("[project.optional-dependencies]")[1].split("[project.scripts]")[0]
    assert "psycopg" in dev_extra
