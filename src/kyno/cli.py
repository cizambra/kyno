from __future__ import annotations

import json
import os
from pathlib import Path

import typer
from sqlalchemy.exc import SQLAlchemyError

from kyno.authoring import ConstitutionFile, read_constitution_file, write_constitution_file
from kyno.config import Settings, store_from_settings
from kyno.errors import CoherenceError
from kyno.public_page import PACKAGED_TEMPLATES, packaged_template
from kyno.service import ControlPlane

app = typer.Typer(help="Coherence engine control plane.")


def _control_plane() -> ControlPlane:
    return ControlPlane(store_from_settings(Settings.from_env()))


def _store():
    return store_from_settings(Settings.from_env())


def _alembic_config(database_url: str):
    """Alembic pointed at the migration scripts that ship inside the package,
    so an installed kyno upgrades its database with no repo checkout around."""
    from importlib import resources

    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", str(resources.files("kyno") / "migrations"))
    # ConfigParser reads % as interpolation; the URL is a value, never a template.
    cfg.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return cfg


@app.command("init-db")
def init_db() -> None:
    """Create the schema on a fresh database, stamped at the current
    migration head so `kyno upgrade-db` can take it from here later."""
    from alembic import command

    try:
        settings = Settings.from_env()
        store_from_settings(settings).create_all()
        command.stamp(_alembic_config(settings.database_url), "head")
        typer.echo("ok")
    except (CoherenceError, SQLAlchemyError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from None


@app.command("upgrade-db")
def upgrade_db() -> None:
    """Bring an existing database up to the current schema."""
    from alembic import command
    from alembic.util.exc import CommandError

    try:
        command.upgrade(_alembic_config(Settings.from_env().database_url), "head")
        typer.echo("ok")
    except (CoherenceError, SQLAlchemyError, CommandError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from None


_CONSTITUTION_OPTION = typer.Option(
    "default", "--constitution", help="Which named constitution to act on."
)


@app.command("set")
def set_direction_cmd(
    note: str | None = typer.Option(None, "--note", help="Plain-language what + why."),
    file: str | None = typer.Option(
        None, "--file", help="Read the constitution from a YAML (or JSON) file."
    ),
    mission: str | None = typer.Option(None, "--mission"),
    declaration: str | None = typer.Option(
        None, "--declaration", help="The long-form document. Use --file for anything longer."
    ),
    principle: list[str] = typer.Option(None, "--principle", help="Repeat for each principle."),
    by: str | None = typer.Option(None, "--by", help="Who made this change."),
    constitution: str | None = typer.Option(
        None, "--constitution", help="Which named constitution to act on."
    ),
) -> None:
    """Append a version. Flags are for quick edits; --file is how a
    constitution with a declaration or described principles gets written."""
    fields = _fields_from(file, mission=mission, declaration=declaration, principle=principle)
    if not note:
        raise typer.BadParameter("a change note is required: pass --note")
    try:
        v = _control_plane().set_direction(
            mission=fields.mission,
            declaration=fields.declaration,
            principles=fields.principles,
            change_note=note,
            created_by=by,
            constitution=constitution or fields.constitution or "default",
        )
        typer.echo(json.dumps(v.to_dict()))
    except (CoherenceError, SQLAlchemyError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from None


def _fields_from(file, *, mission, declaration, principle) -> ConstitutionFile:
    """The content of an edit, from the file or the content flags, never
    both. A file holds content only; --note, --by and --constitution
    describe the edit and always come from the command line."""
    if file is None:
        return ConstitutionFile(
            mission=mission,
            declaration=declaration,
            principles=tuple(principle) if principle else None,
        )
    given = (("--mission", mission is not None), ("--declaration", declaration is not None))
    conflicting = [
        flag for flag, was_given in (*given, ("--principle", bool(principle))) if was_given
    ]
    if conflicting:
        raise typer.BadParameter(
            f"--file cannot be combined with {', '.join(conflicting)}; "
            "a file holds content only, and --note, --by and --constitution "
            "describe the edit"
        )
    try:
        return read_constitution_file(file)
    except CoherenceError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from None


page_app = typer.Typer(help="Work with the pages Kyno publishes.")
app.add_typer(page_app, name="page")


@page_app.command("export")
def page_export(
    directory: str = typer.Argument(..., help="Where to write the copies."),
) -> None:
    """Copy the default pages out so you can edit them.

    What you get is what Kyno renders: the same files it fills, in the same
    placeholder syntax. Edit them, point the environment variables at your
    copies, and yours are served instead.
    """
    target = Path(directory)
    existing = [name for name in PACKAGED_TEMPLATES if (target / name).exists()]
    if existing:
        # All or nothing: a half-written export would leave an operator
        # guessing which of the files in front of them are still theirs.
        typer.echo(
            f"error: {target} already has {', '.join(existing)}; "
            "nothing written. Export somewhere else, or move them aside.",
            err=True,
        )
        raise typer.Exit(code=1)
    try:
        target.mkdir(parents=True, exist_ok=True)
        for name in PACKAGED_TEMPLATES:
            # "x": refuse anything that appeared since the check, including a
            # dangling symlink the exists() check cannot see -- O_EXCL refuses
            # to follow one rather than planting a file where it points.
            with (target / name).open("x", encoding="utf-8") as handle:
                handle.write(packaged_template(name))
    except FileExistsError:
        typer.echo(
            f"error: {name} appeared in {target} while exporting; nothing was "
            "overwritten, and the files already exported were left for you to inspect.",
            err=True,
        )
        raise typer.Exit(code=1) from None
    except OSError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from None

    typer.echo(f"wrote {len(PACKAGED_TEMPLATES)} files to {target}")
    for name in PACKAGED_TEMPLATES:
        typer.echo(f"  {name}")
    typer.echo("\nedit them, then point kyno at your copies:")
    typer.echo(f"  export KYNO_CONSTITUTION_TEMPLATE={(target / 'constitution.html').resolve()}")
    typer.echo(f"  export KYNO_INDEX_TEMPLATE={(target / 'index.html').resolve()}")
    typer.echo(
        "\npage.css is a starting point for your own template's styles -- link or "
        "inline it yourself.\nThe $stylesheet placeholder always serves the styles "
        "built into kyno, not this copy."
    )


@app.command()
def current(constitution: str = _CONSTITUTION_OPTION) -> None:
    try:
        v = _control_plane().current(constitution)
        if v.version == 0:
            typer.echo("no constitution set (version 0)")
        else:
            typer.echo(json.dumps(v.to_dict()))
    except (CoherenceError, SQLAlchemyError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from None


@app.command()
def pull(
    file: str = typer.Argument(..., help="Where to write the snapshot."),
    constitution: str = _CONSTITUTION_OPTION,
) -> None:
    """Write the current version into a file, replacing what the file held.

    The inverse of `kyno set --file`: after a pull, the file says exactly
    what the store serves. Run it when the file may be stale -- after a
    flags-only edit, or after somebody else applied a change."""
    try:
        v = _control_plane().current(constitution)
        if v.version == 0:
            typer.echo(f"error: nothing to pull: '{constitution}' has no versions", err=True)
            raise typer.Exit(code=1)
        write_constitution_file(file, v, constitution)
        typer.echo(f"pulled {constitution} v{v.version} into {file}")
    except (CoherenceError, SQLAlchemyError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from None


@app.command()
def publish(
    constitution: str = _CONSTITUTION_OPTION,
    with_history: bool = typer.Option(
        False,
        "--with-history",
        help="Also publish the version history and its change notes.",
    ),
) -> None:
    """Serve a constitution publicly. Without --with-history only the current
    mission, principles, version and last-changed date are exposed."""
    try:
        pub = _control_plane().publish(constitution, with_history=with_history)
        history = "public" if pub.history_public else "hidden"
        typer.echo(f"published '{constitution}' (history: {history})")
        typer.echo(f"  GET /constitutions/{constitution}")
        typer.echo(f"  GET /constitutions/{constitution}.json")
    except (CoherenceError, SQLAlchemyError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from None


@app.command()
def unpublish(constitution: str = _CONSTITUTION_OPTION) -> None:
    """Take a constitution's public page down. History goes private too."""
    try:
        _control_plane().unpublish(constitution)
        typer.echo(f"unpublished '{constitution}'")
    except (CoherenceError, SQLAlchemyError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from None


@app.command()
def export(
    from_version: int | None = typer.Option(
        None, "--from", help="First version to include (inclusive)."
    ),
    to_version: int | None = typer.Option(
        None, "--to", help="Last version to include (inclusive)."
    ),
    constitution: str = _CONSTITUTION_OPTION,
) -> None:
    try:
        rows = _store().export_versions(
            constitution, from_version=from_version, to_version=to_version
        )
        typer.echo(json.dumps(rows, indent=2))
    except (CoherenceError, SQLAlchemyError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from None


@app.command()
def serve(transport: str = typer.Option("stdio", "--transport")) -> None:
    try:
        settings = Settings.from_env()
    except CoherenceError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from None
    cp = ControlPlane(store_from_settings(settings))
    if transport == "stdio":
        import anyio

        from kyno.transports import run_stdio

        anyio.run(run_stdio, cp)
    elif transport == "http":
        allow_insecure = os.environ.get("KYNO_ALLOW_INSECURE_HTTP", "").lower() in ("1", "true")
        if settings.token is None and not allow_insecure:
            raise typer.BadParameter(
                "refusing to serve HTTP without a token: set KYNO_TOKEN, "
                "or set KYNO_ALLOW_INSECURE_HTTP=1 to override for local use"
            )
        if settings.token is None:
            typer.echo(
                "WARNING: serving HTTP with no KYNO_TOKEN set "
                "(KYNO_ALLOW_INSECURE_HTTP is set) — the constitution can be "
                "rewritten by anyone who can reach this endpoint",
                err=True,
            )
        import uvicorn

        from kyno.transports import build_http_app

        uvicorn.run(
            build_http_app(cp, settings.token, settings.page, allow_insecure=allow_insecure),
            host=settings.host,
            port=settings.port,
        )
    else:
        raise typer.BadParameter("transport must be 'stdio' or 'http'")
