from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from typer.testing import CliRunner

from tests.workspaces import cli_workspace

TABLES = {"kyno_constitutions", "kyno_constitution_versions"}


def _colmap(insp, table):
    # name -> nullable; compares presence + nullability across schemas
    return {c["name"]: bool(c["nullable"]) for c in insp.get_columns(table)}


def _has_version_uniqueness(insp, versions_table):
    cols = {"constitution_id", "version"}
    for uc in insp.get_unique_constraints(versions_table):
        if set(uc["column_names"]) == cols:
            return True
    for ix in insp.get_indexes(versions_table):
        if ix.get("unique") and set(ix["column_names"]) == cols:
            return True
    return False


def test_given_a_fresh_database_when_alembic_upgrades_then_the_expected_tables_exist(tmp_path):
    db = tmp_path / "m.sqlite3"
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db}")
    command.upgrade(cfg, "head")
    insp = inspect(create_engine(f"sqlite:///{db}"))
    tables = set(insp.get_table_names())
    assert {"kyno_constitutions", "kyno_constitution_versions"} <= tables


def test_given_an_upgraded_database_when_downgrading_and_upgrading_then_the_schema_round_trips(
    tmp_path,
):
    # A stray table left by downgrade would silently survive a "reset the DB" workflow.
    db = tmp_path / "roundtrip.sqlite3"
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db}")
    engine = create_engine(f"sqlite:///{db}")
    tables = {"kyno_constitutions", "kyno_constitution_versions"}

    command.upgrade(cfg, "head")
    assert tables <= set(inspect(engine).get_table_names())

    command.downgrade(cfg, "base")
    remaining = set(inspect(engine).get_table_names())
    assert not (tables & remaining), f"downgrade left tables behind: {tables & remaining}"

    command.upgrade(cfg, "head")
    insp = inspect(engine)
    restored = set(insp.get_table_names())
    assert tables <= restored

    from kyno.store.sql import SqlConstitutionStore

    edb = tmp_path / "embedded_for_roundtrip.sqlite3"
    store = SqlConstitutionStore(url=f"sqlite:///{edb}")
    store.create_all()
    einsp = inspect(store.engine)

    for t in tables:
        assert _colmap(insp, t) == _colmap(einsp, t), f"schema drift in {t} after re-upgrade"

    versions_table = "kyno_constitution_versions"
    assert _has_version_uniqueness(insp, versions_table)
    assert _has_version_uniqueness(einsp, versions_table)


def test_given_the_migration_and_the_embedded_schema_when_comparing_then_they_are_identical(
    tmp_path,
):
    from kyno.store.sql import SqlConstitutionStore

    mdb = tmp_path / "migrated.sqlite3"
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{mdb}")
    command.upgrade(cfg, "head")
    minsp = inspect(create_engine(f"sqlite:///{mdb}"))

    edb = tmp_path / "embedded.sqlite3"
    store = SqlConstitutionStore(url=f"sqlite:///{edb}")
    store.create_all()
    einsp = inspect(store.engine)

    tables = {"kyno_constitutions", "kyno_constitution_versions"}
    assert tables <= set(minsp.get_table_names())
    assert tables <= set(einsp.get_table_names())

    for t in tables:
        assert _colmap(minsp, t) == _colmap(einsp, t), f"schema drift in {t}"

    # Column names alone would miss a migration silently dropping the uniqueness
    # rule that makes concurrent writers safe (the loser retries).
    versions_table = "kyno_constitution_versions"

    assert _has_version_uniqueness(minsp, versions_table), (
        "migrated schema is missing the (constitution_id, version) unique constraint/index"
    )
    assert _has_version_uniqueness(einsp, versions_table), (
        "embedded create_all schema is missing the (constitution_id, "
        "version) unique constraint/index"
    )


def test_given_the_two_schema_paths_when_comparing_then_both_carry_the_publication_columns(
    tmp_path,
):
    # Publication state decides what an anonymous visitor can see. A migration
    # that lost these columns would fail open on one deployment and not the other.
    from kyno.store.sql import SqlConstitutionStore

    mdb = tmp_path / "pub_migrated.sqlite3"
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{mdb}")
    command.upgrade(cfg, "head")
    minsp = inspect(create_engine(f"sqlite:///{mdb}"))

    edb = tmp_path / "pub_embedded.sqlite3"
    store = SqlConstitutionStore(url=f"sqlite:///{edb}")
    store.create_all()
    einsp = inspect(store.engine)

    table = "kyno_constitutions"
    for insp, label in ((minsp, "migrated"), (einsp, "embedded")):
        cols = _colmap(insp, table)
        assert "published_at" in cols, f"{label} schema is missing published_at"
        assert "history_public" in cols, f"{label} schema is missing history_public"
        assert cols["published_at"] is True, (
            f"{label}: published_at must be nullable (null = private)"
        )
        assert cols["history_public"] is False, f"{label}: history_public must be NOT NULL"


def test_given_an_existing_database_when_upgrading_then_its_constitutions_stay_private(tmp_path):
    # The realistic upgrade: a store that already holds constitutions gains
    # the publication columns, and every existing one stays private.
    from kyno.service import ControlPlane
    from kyno.store.sql import SqlConstitutionStore

    db = tmp_path / "existing.sqlite3"
    url = f"sqlite:///{db}"
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)

    command.upgrade(cfg, "0001")
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO kyno_constitutions (name, current_version, created_at) "
            "VALUES ('legacy', 1, '2026-01-01 00:00:00')"
        )
        conn.exec_driver_sql(
            "INSERT INTO kyno_constitution_versions (constitution_id, version, mission, "
            "principles, change_note, changed_mission, changed_principles, created_at) "
            "VALUES (1, 1, 'Old mission', '[\"p1\"]', 'init', 1, 1, '2026-01-01 00:00:00')"
        )

    command.upgrade(cfg, "head")

    plane = ControlPlane(SqlConstitutionStore(url=url))
    assert plane.current("legacy").mission == "Old mission"
    assert plane.publication("legacy").published is False
    assert plane.public_constitution("legacy") is None
    assert plane.published_constitutions() == ()


def test_given_the_two_schema_paths_when_comparing_then_both_carry_the_declaration_column(tmp_path):
    # The declaration is the long-form document; a deployment whose schema
    # lost it would silently serve constitutions with their body missing.
    from kyno.store.sql import SqlConstitutionStore

    mdb = tmp_path / "decl_migrated.sqlite3"
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{mdb}")
    command.upgrade(cfg, "head")
    minsp = inspect(create_engine(f"sqlite:///{mdb}"))

    edb = tmp_path / "decl_embedded.sqlite3"
    store = SqlConstitutionStore(url=f"sqlite:///{edb}")
    store.create_all()
    einsp = inspect(store.engine)

    table = "kyno_constitution_versions"
    for insp, label in ((minsp, "migrated"), (einsp, "embedded")):
        cols = _colmap(insp, table)
        assert "declaration" in cols, f"{label} schema is missing declaration"
        assert cols["declaration"] is True, (
            f"{label}: declaration must be nullable (null = never written)"
        )


def test_given_an_existing_database_when_upgrading_then_its_versions_stay_undeclared(tmp_path):
    # The realistic upgrade again, one migration later: rows written before
    # declarations existed keep serving, with no declaration.
    from kyno.service import ControlPlane
    from kyno.store.sql import SqlConstitutionStore

    db = tmp_path / "pre_declaration.sqlite3"
    url = f"sqlite:///{db}"
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)

    command.upgrade(cfg, "0002")
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO kyno_constitutions (name, current_version, created_at) "
            "VALUES ('legacy', 1, '2026-01-01 00:00:00')"
        )
        conn.exec_driver_sql(
            "INSERT INTO kyno_constitution_versions (constitution_id, version, mission, "
            "principles, change_note, changed_mission, changed_principles, created_at) "
            "VALUES (1, 1, 'Old mission', '[\"p1\"]', 'init', 1, 1, '2026-01-01 00:00:00')"
        )

    command.upgrade(cfg, "head")

    plane = ControlPlane(SqlConstitutionStore(url=url))
    head = plane.current("legacy")
    assert head.mission == "Old mission"
    assert head.declaration == ""
    assert [p.title for p in head.principles] == ["p1"]


def _point_cli_at(monkeypatch, tmp_path, name):
    url = f"sqlite:///{tmp_path / name}"
    cli_workspace(monkeypatch, tmp_path, tmp_path / name)
    return url


def _packaged_scripts():
    from importlib import resources

    return str(resources.files("kyno") / "migrations")


def test_given_a_fresh_database_when_running_upgrade_db_then_it_reaches_head(tmp_path, monkeypatch):
    from kyno.cli import app

    url = _point_cli_at(monkeypatch, tmp_path, "fresh.sqlite3")

    result = CliRunner().invoke(app, ["db", "upgrade"])

    assert result.exit_code == 0, result.output
    assert set(inspect(create_engine(url)).get_table_names()) >= TABLES


def test_given_the_packaged_scripts_when_running_upgrade_db_then_those_scripts_run():
    # Pinned so a pip-installed kyno, with no repo checkout around, can
    # always find its own migration scripts.
    from kyno.cli import _alembic_config

    cfg = _alembic_config("sqlite://")

    assert cfg.get_main_option("script_location") == _packaged_scripts()


def test_given_a_fresh_database_when_running_init_db_then_it_is_stamped_at_head(
    tmp_path, monkeypatch
):
    from alembic.script import ScriptDirectory

    from kyno.cli import app

    url = _point_cli_at(monkeypatch, tmp_path, "stamped.sqlite3")

    result = CliRunner().invoke(app, ["db", "init"])

    assert result.exit_code == 0, result.output
    with create_engine(url).connect() as conn:
        stamped = conn.exec_driver_sql("SELECT version_num FROM alembic_version").scalar()
    assert stamped == ScriptDirectory(_packaged_scripts()).get_current_head()


def test_given_an_init_db_database_when_running_upgrade_db_later_then_it_upgrades_cleanly(
    tmp_path, monkeypatch
):
    from kyno.cli import app

    url = _point_cli_at(monkeypatch, tmp_path, "roundtrip.sqlite3")
    runner = CliRunner()

    assert runner.invoke(app, ["db", "init"]).exit_code == 0
    result = runner.invoke(app, ["db", "upgrade"])

    assert result.exit_code == 0, result.output
    assert set(inspect(create_engine(url)).get_table_names()) >= TABLES


def test_given_a_pre_declaration_database_when_a_pip_user_upgrades_then_it_upgrades_cleanly(
    tmp_path, monkeypatch
):
    # The whole flow: a database built two schema generations ago, holding
    # real rows, brought to the current schema by the CLI alone.
    from kyno.cli import app
    from kyno.service import ControlPlane
    from kyno.store.sql import SqlConstitutionStore

    db = tmp_path / "old.sqlite3"
    url = f"sqlite:///{db}"
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "0002")
    with create_engine(url).begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO kyno_constitutions (name, current_version, created_at) "
            "VALUES ('legacy', 1, '2026-01-01 00:00:00')"
        )
        conn.exec_driver_sql(
            "INSERT INTO kyno_constitution_versions (constitution_id, version, mission, "
            "principles, change_note, changed_mission, changed_principles, created_at) "
            "VALUES (1, 1, 'Old mission', '[\"p1\"]', 'init', 1, 1, '2026-01-01 00:00:00')"
        )
    cli_workspace(monkeypatch, tmp_path, db)

    result = CliRunner().invoke(app, ["db", "upgrade"])

    assert result.exit_code == 0, result.output
    head = ControlPlane(SqlConstitutionStore(url=url)).current("legacy")
    assert head.mission == "Old mission"
    assert head.declaration == ""


def test_given_a_head_database_when_downgrading_one_migration_then_only_its_own_column_is_dropped(
    tmp_path,
):
    # A downgrade that took a neighbouring column with it would lose data
    # nobody asked to lose.
    db = tmp_path / "step_down.sqlite3"
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db}")
    engine = create_engine(f"sqlite:///{db}")
    table = "kyno_constitution_versions"

    command.upgrade(cfg, "head")
    before = _colmap(inspect(engine), table)

    command.downgrade(cfg, "0003")
    after = _colmap(inspect(engine), table)
    assert set(before) - set(after) == {"authorized_by"}

    command.downgrade(cfg, "0002")
    after = _colmap(inspect(engine), table)
    assert set(before) - set(after) == {"authorized_by", "declaration"}

    command.upgrade(cfg, "head")
    assert _colmap(inspect(engine), table) == before


def test_given_migrated_and_create_all_databases_when_comparing_then_both_carry_authorized_by(
    tmp_path,
):
    from kyno.store.sql import SqlConstitutionStore

    mdb = tmp_path / "auth_migrated.sqlite3"
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{mdb}")
    command.upgrade(cfg, "head")
    minsp = inspect(create_engine(f"sqlite:///{mdb}"))

    edb = tmp_path / "auth_embedded.sqlite3"
    store = SqlConstitutionStore(url=f"sqlite:///{edb}")
    store.create_all()
    einsp = inspect(store.engine)

    table = "kyno_constitution_versions"
    for insp, label in ((minsp, "migrated"), (einsp, "embedded")):
        cols = _colmap(insp, table)
        assert "authorized_by" in cols, f"{label} schema is missing authorized"
        assert cols["authorized_by"] is True, (
            f"{label}: authorized_by must be nullable (null = nothing to record)"
        )


def test_given_an_existing_database_when_upgrading_then_its_versions_stay_unauthorized(tmp_path):
    # The realistic upgrade one migration later: rows written before the
    # questions existed keep serving, recording nothing.
    from kyno.service import ControlPlane
    from kyno.store.sql import SqlConstitutionStore

    db = tmp_path / "pre_authorized.sqlite3"
    url = f"sqlite:///{db}"
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)

    command.upgrade(cfg, "0003")
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO kyno_constitutions (name, current_version, created_at) "
            "VALUES ('legacy', 1, '2026-01-01 00:00:00')"
        )
        conn.exec_driver_sql(
            "INSERT INTO kyno_constitution_versions (constitution_id, version, mission, "
            "principles, change_note, changed_mission, changed_principles, created_at) "
            "VALUES (1, 1, 'Old mission', '[\"p1\"]', 'init', 1, 1, '2026-01-01 00:00:00')"
        )

    command.upgrade(cfg, "head")

    head = ControlPlane(SqlConstitutionStore(url=url)).current("legacy")
    assert head.mission == "Old mission"
    assert head.authorized_by is None
