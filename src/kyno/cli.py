from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import typer
from sqlalchemy.exc import SQLAlchemyError

from kyno.authoring import (
    ConstitutionFile,
    check_constitution_file,
    read_constitution_file,
    render_constitution_yaml,
)
from kyno.config import Settings, store_from_settings
from kyno.errors import AuthoringError, CoherenceError, NoFieldChangedError
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
    file: str = typer.Argument(..., help="The constitution file. The only source of content."),
    note: str | None = typer.Option(None, "--note", help="What changed in this new version?"),
    by: str | None = typer.Option(
        None, "--by", help="Who made this change. Defaults to your system username."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Print what would change, apply nothing."
    ),
) -> None:
    """Append a version from a file. The file says what the constitution
    is, including which one it is; the flags say what this edit is. Every
    apply prints the delta it makes; --dry-run prints it and stops."""
    if not dry_run and not (note and note.strip()):
        raise typer.BadParameter("a change note is required: pass --note")
    with _clean_errors():
        fields = read_constitution_file(file)
        content = _content_of(fields)
        target = _constitution_name(fields, file)
        plane = _control_plane()
        delta = plane.preview_edit(**content, constitution=target)
        if dry_run:
            _print_delta(delta or ("no field changed",))
            return
        # The delta goes to stderr so stdout stays the version JSON, pipeable.
        _print_delta(delta, err=True)
        try:
            version = plane.set_direction(
                **content,
                change_note=note,
                created_by=by if by is not None else _system_user(),
                constitution=target,
            )
        except NoFieldChangedError:
            # The store already says what the file says. Reruns and duplicate
            # applies are the normal case, so this is a clean exit: the head
            # in force prints, the same as if it had just been written.
            typer.echo("no field changed", err=True)
            version = plane.current(target)
        typer.echo(json.dumps(version.to_dict(), indent=2))


@contextmanager
def _clean_errors() -> Iterator[None]:
    """Kyno's own errors and database failures end the command with one
    line on stderr and exit 1, never a traceback."""
    try:
        yield
    except (CoherenceError, SQLAlchemyError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from None


def _constitution_name(fields: ConstitutionFile, path: str) -> str:
    """Which constitution the file belongs to, read from its `constitution:`
    key. The key is required: without it, a file could be applied to the
    wrong constitution by accident, so the file is refused instead and the
    message says what line to add."""
    if not fields.constitution:
        raise AuthoringError(
            f"{path}: the file does not say which constitution it is; "
            "add a 'constitution: <name>' line ('default' if you keep only one)"
        )
    return fields.constitution


def _content_of(fields: ConstitutionFile) -> dict[str, object]:
    """The content fields as keyword arguments, so the preview and the
    apply are guaranteed to describe the same edit."""
    return {
        "mission": fields.mission,
        "declaration": fields.declaration,
        "principles": fields.principles,
    }


def _print_delta(lines: tuple[str, ...], *, err: bool = False) -> None:
    for line in lines:
        typer.echo(line, err=err)


def _system_user() -> str | None:
    """Git's fallback for an unstated author: the person at the keyboard."""
    import getpass

    try:
        return getpass.getuser()
    except (KeyError, OSError):
        return None


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
def current(
    constitution: str = _CONSTITUTION_OPTION,
    as_yaml: bool = typer.Option(
        False,
        "--yaml",
        help="Print the head in the file format `kyno set --file` reads.",
    ),
) -> None:
    """The version in force. JSON by default; --yaml prints it as a
    constitution file, ready to redirect, commit, and re-apply."""
    try:
        v = _control_plane().current(constitution)
        if v.version == 0:
            if as_yaml:
                typer.echo(f"error: nothing to read: '{constitution}' has no versions", err=True)
                raise typer.Exit(code=1)
            typer.echo("no constitution set (version 0)")
        elif as_yaml:
            typer.echo(render_constitution_yaml(v, constitution), nl=False)
        else:
            typer.echo(json.dumps(v.to_dict(), indent=2))
    except (CoherenceError, SQLAlchemyError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from None


@app.command()
def check(
    file: str = typer.Argument(..., help="The constitution file to inspect."),
) -> None:
    """Report which kyno fields a file sets, which it leaves out, and which
    keys are yours. Nothing here blocks an apply: a field the file leaves
    out keeps the previous version's value, and a custom key is ignored."""
    try:
        report = check_constitution_file(file)
    except CoherenceError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from None
    typer.echo(f"kyno fields set: {', '.join(report.present) or 'none'}")
    typer.echo(f"kyno fields not set: {', '.join(report.missing) or 'none'}")
    typer.echo(f"custom fields: {', '.join(report.custom) or 'none'}")


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
