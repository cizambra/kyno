from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
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
from kyno.models import AUTOMATION, OPERATOR, OVERRIDE, SCOPES, normalize_principles
from kyno.profiles import (
    add_credentials,
    add_remote,
    credentials_path,
    inspect,
    remotes,
    remotes_path,
)
from kyno.public_page import PACKAGED_TEMPLATES, packaged_template
from kyno.remote import RemoteError, dial, version_from_payload
from kyno.service import ControlPlane, edit_delta, effective_content
from kyno.tokens import age, generate_value, hash_value, parse_ttl
from kyno.workspace import create_workspace

app = typer.Typer(help="Coherence engine control plane.")


def _control_plane() -> ControlPlane:
    return ControlPlane(store_from_settings(Settings.load()))


def _store():
    return store_from_settings(Settings.load())


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


db_app = typer.Typer(help="The database under this workspace's store.")
app.add_typer(db_app, name="db")


@db_app.command("init")
def db_init() -> None:
    """Create the schema on a fresh database, stamped at the current
    migration head so `kyno db upgrade` can take it from here later."""
    from alembic import command

    try:
        settings = Settings.load()
        store_from_settings(settings).create_all()
        command.stamp(_alembic_config(settings.database_url), "head")
        typer.echo("ok")
    except (CoherenceError, SQLAlchemyError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from None


@db_app.command("upgrade")
def db_upgrade() -> None:
    """Bring an existing database up to the current schema."""
    from alembic import command
    from alembic.util.exc import CommandError

    try:
        command.upgrade(_alembic_config(Settings.load().database_url), "head")
        typer.echo("ok")
    except (CoherenceError, SQLAlchemyError, CommandError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from None


token_app = typer.Typer(help="The tokens this server accepts: mint, list, revoke.")
app.add_typer(token_app, name="token")


@token_app.command("add")
def token_add(
    name: str = typer.Argument(..., help="A label for humans. The id is the identity."),
    scope: str = typer.Option(
        ..., "--scope", help="read: every tool except set_direction. write: everything."
    ),
    ttl: str | None = typer.Option(
        None, "--ttl", help="Expire on its own after this long (30m, 2h, 7d)."
    ),
) -> None:
    """Mint a token: prints the value, once. Only its hash is stored."""
    if scope not in SCOPES:
        typer.echo(f"error: unknown scope '{scope}': choose read or write", err=True)
        raise typer.Exit(code=1)
    expires_at = None
    if ttl is not None:
        try:
            expires_at = datetime.now(UTC) + parse_ttl(ttl)
        except ValueError as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(code=1) from None
    value = generate_value()
    try:
        _store().add_token(name, scope, token_hash=hash_value(value), expires_at=expires_at)
    except (CoherenceError, SQLAlchemyError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from None
    typer.echo(value)


@token_app.command("list")
def token_list(
    all_tokens: bool = typer.Option(False, "--all", help="Include revoked and expired tokens."),
) -> None:
    """Live tokens, one line each: id, name, scope, created, last used."""
    try:
        rows = _store().tokens()
    except (CoherenceError, SQLAlchemyError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from None
    now = datetime.now(UTC)
    if not all_tokens:
        rows = [t for t in rows if t.live_at(now)]
    if not rows:
        if all_tokens:
            typer.echo("no tokens")
        else:
            typer.echo("no live tokens; mint one with: kyno token add NAME --scope write")
        return
    id_w = max(len(str(t.id)) for t in rows)
    name_w = max(len(t.name) for t in rows)
    scope_w = max(len(t.scope) for t in rows)
    for t in rows:
        line = (
            f"{t.id:<{id_w}}  {t.name:<{name_w}}  {t.scope:<{scope_w}}  "
            f"created {t.created_at.date().isoformat()}  last used {age(t.last_used_at, now)}"
        )
        # Only --all reaches a dead row; the default list holds live tokens only.
        if t.revoked_at is not None:
            line += "  revoked"
        elif not t.live_at(now):
            line += "  expired"
        typer.echo(line)


@token_app.command("revoke")
def token_revoke(
    name: str | None = typer.Argument(
        None, help="The token's name; use --id when two live tokens share it."
    ),
    token_id: int | None = typer.Option(None, "--id", help="The token's id, from kyno token list."),
) -> None:
    """Revoke a token: it stops working now, and its row stays for history."""
    if (name is None) == (token_id is None):
        typer.echo("error: name the token one way: its name, or --id", err=True)
        raise typer.Exit(code=1)
    try:
        store = _store()
        if token_id is None:
            now = datetime.now(UTC)
            live = [t for t in store.tokens() if t.name == name and t.live_at(now)]
            if not live:
                typer.echo(f"error: no live token named '{name}'", err=True)
                raise typer.Exit(code=1)
            if len(live) > 1:
                ids = ", ".join(str(t.id) for t in live)
                typer.echo(
                    f"error: {len(live)} live tokens are named '{name}' (ids {ids}); "
                    "pick one with --id",
                    err=True,
                )
                raise typer.Exit(code=1)
            token_id = live[0].id
        token = store.token(token_id)
        if token is None:
            typer.echo(f"error: no token with id {token_id}", err=True)
            raise typer.Exit(code=1)
        if token.revoked_at is not None:
            typer.echo(f"error: token id {token_id} is already revoked", err=True)
            raise typer.Exit(code=1)
        if not token.live_at(datetime.now(UTC)):
            # Revoking sets a timestamp meaning "stopped working now".
            # An expired token already stopped, so stamping it would record
            # the wrong cause.
            typer.echo(f"error: token id {token_id} already expired", err=True)
            raise typer.Exit(code=1)
        store.revoke_token(token_id)
        typer.echo(f"revoked id {token_id}")
    except (CoherenceError, SQLAlchemyError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from None


_CONSTITUTION_OPTION = typer.Option(
    "default", "--constitution", help="Which named constitution to act on."
)

_REMOTE_HELP = "Run against a remote profile's endpoint instead of the local store."


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
    remote: bool = typer.Option(False, "--remote", help=_REMOTE_HELP),
    profile: str = typer.Option("default", "--profile", help="Which remote profile to use."),
    credentials: str | None = typer.Option(
        None, "--credentials", help="Take the token from this credentials profile, this run."
    ),
    token_env: str | None = typer.Option(
        None, "--token-env", help="Take the token from this variable, this run."
    ),
    no_interactive: bool = typer.Option(
        False, "--no-interactive", help="Tells Kyno nobody is at the keyboard, so it never asks."
    ),
    unsafe_approval: bool = typer.Option(
        False, "--unsafe-approval", help="Skip the questions, answering yes to all of them."
    ),
) -> None:
    """Append a version from a file. The file says what the constitution
    is, including which one it is; the flags say what this edit is. Every
    apply prints the delta it makes; --dry-run prints it and stops."""
    if not dry_run and not (note and note.strip()):
        raise typer.BadParameter("a change note is required: pass --note")
    _remote_options_guard(remote, profile, credentials, token_env)
    if not remote and (no_interactive or unsafe_approval):
        raise typer.BadParameter(
            "--no-interactive and --unsafe-approval are for remote runs; add --remote"
        )
    if unsafe_approval and no_interactive:
        raise typer.BadParameter(
            "pick one: --no-interactive skips the questions; "
            "--unsafe-approval skips them answering yes to all"
        )
    with _clean_errors():
        fields = read_constitution_file(file)
        content = _content_of(fields)
        target = _constitution_name(fields, file)
        if remote:
            _remote_set(
                target,
                content,
                note,
                by,
                dry_run,
                profile,
                credentials,
                token_env,
                no_interactive=no_interactive,
                unsafe_approval=unsafe_approval,
            )
            return
        plane = _control_plane()
        head, delta = plane.head_and_delta(**content, constitution=target)
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
                # The write lands on the head the delta described, or not at all.
                expected_version=head.version if head else 0,
            )
        except NoFieldChangedError:
            # The store already says what the file says. Reruns and duplicate
            # applies are the normal case, so this is a clean exit: the head
            # in force prints, the same as if it had just been written.
            typer.echo("no field changed", err=True)
            version = plane.current(target)
        typer.echo(json.dumps(version.to_dict(), indent=2))


def _remote_set(
    target: str,
    content: dict,
    note: str | None,
    by: str | None,
    dry_run: bool,
    profile: str,
    credentials: str | None,
    token_env: str | None,
    *,
    no_interactive: bool = False,
    unsafe_approval: bool = False,
) -> None:
    """The local apply, spoken over the wire: fetch the head, show the same
    delta the local path would show, then ask the server to append."""
    client = dial(profile, credentials_profile=credentials, token_env=token_env)
    try:
        payload = _fetch_remote_head(client, target)
        head = version_from_payload(payload)
        delta = edit_delta(head, target, **content)
        if dry_run:
            _print_delta(delta or ("no field changed",))
            return
        _print_delta(delta, err=True)
        _answer_consent(target, client.url, no_interactive, unsafe_approval)
        if not no_interactive and not unsafe_approval:
            _answer_revert_signature(client, target, head, content)
        principles = content["principles"]
        arguments = {
            "mission": content["mission"],
            "declaration": content["declaration"],
            "principles": (
                None
                if principles is None
                else [{"title": p.title, "description": p.description} for p in principles]
            ),
            "change_note": note,
            "created_by": by if by is not None else _system_user(),
            "constitution": target,
            # The write lands on the head the delta described, or not at all.
            "expected_version": head.version if head else 0,
            # Who stood behind this write, recorded on the version: an
            # operator answered, automation ran, or the override flag did.
            "authorized_by": (
                OVERRIDE if unsafe_approval else AUTOMATION if no_interactive else OPERATOR
            ),
        }
        try:
            result = client.call_tool("set_direction", arguments)
        except RemoteError as refusal:
            if "no field changed" not in str(refusal):
                raise
            # Same clean no-op as the local path: the head in force prints.
            typer.echo("no field changed", err=True)
            result = payload
        typer.echo(json.dumps(result, indent=2))
    finally:
        client.close()


def _answer_consent(target: str, url: str, no_interactive: bool, unsafe_approval: bool) -> None:
    """Asks the consent question on interactive remote applies.
    --no-interactive skips the questions; --unsafe-approval skips them
    answering yes to all. If the answer is no, nothing is applied."""
    if no_interactive or unsafe_approval:
        return
    typer.echo(f"You are applying to '{target}' at {url}.", err=True)
    typer.echo("Every agent using it will follow this change on its next pull.", err=True)
    try:
        answered_yes = typer.confirm(
            "Have you evaluated it against your workflow?", default=False, err=True
        )
    except typer.Abort:
        # stdin is closed, so nobody can answer the question.
        typer.echo(
            "not applied: the consent question had nobody to answer it; "
            "pass --no-interactive on a machine, "
            "or --unsafe-approval to answer yes to everything",
            err=True,
        )
        raise typer.Exit(code=1) from None
    if not answered_yes:
        typer.echo("not applied: the consent question was answered no", err=True)
        raise typer.Exit(code=1)


def _answer_revert_signature(client, target: str, head, content: dict) -> None:
    """Asks whether this is a deliberate revert when the file has the same
    content as an older version. Only on interactive remote applies: a
    headless run can't tell a deliberate revert from a stale file, so it
    isn't asked."""
    if head is None:
        return
    match = _matching_older_version(client, target, head, content)
    if match is None:
        return
    typer.echo(f"This file has exactly the same content as v{match}.", err=True)
    typer.echo(f"Applying it will bring that content back as v{head.version + 1}.", err=True)
    try:
        answered_yes = typer.confirm("Is this a deliberate revert?", default=False, err=True)
    except typer.Abort:
        typer.echo("not applied: the revert question had nobody to answer it", err=True)
        raise typer.Exit(code=1) from None
    if not answered_yes:
        typer.echo("not applied: the revert question was answered no", err=True)
        raise typer.Exit(code=1)


def _matching_older_version(client, target: str, head, content: dict) -> int | None:
    """The newest version below the head whose content is the same as what
    this apply would write, or None when there is no match."""
    rows = client.call_tool("export_versions", {"constitution": target})
    incoming = effective_content(head, **content)
    match = None
    for row in rows:
        if row["version"] < head.version and _row_content(row) == incoming:
            match = row["version"]
    return match


def _row_content(row: dict) -> tuple:
    """One exported version's content fields, normalized for comparison."""
    return (
        row.get("mission") or "",
        row.get("declaration") or "",
        tuple(normalize_principles(tuple(row.get("principles") or ()))),
    )


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


def _remote_options_guard(
    remote: bool, profile: str, credentials: str | None, token_env: str | None
) -> None:
    if not remote and (profile != "default" or credentials is not None or token_env is not None):
        raise typer.BadParameter(
            "--profile, --credentials and --token-env are for remote runs; add --remote"
        )


def _fetch_remote_head(client, constitution: str) -> dict:
    return client.call_tool("get_constitution", {"constitution": constitution, "detail": "full"})


def _system_user() -> str | None:
    """Git's fallback for an unstated author: the person at the keyboard."""
    import getpass

    try:
        return getpass.getuser()
    except (KeyError, OSError):
        return None


page_app = typer.Typer(help="Work with the pages Kyno publishes.")
app.add_typer(page_app, name="page")

remote_app = typer.Typer(help="Where a remote run goes: one profile per destination.")
app.add_typer(remote_app, name="remote")

credentials_app = typer.Typer(help="The tokens remote runs use: one profile per token.")
app.add_typer(credentials_app, name="credentials")


@credentials_app.command("add")
def credentials_add(
    profile: str = typer.Option("default", "--profile", help="The credentials profile to write."),
    token_env: str | None = typer.Option(
        None, "--token-env", help="Read the token from this variable at use time."
    ),
) -> None:
    """Add or replace one credentials profile. Without --token-env the token
    is asked for with hidden input; it is never a command-line flag."""
    token = None
    if token_env is None:
        token = typer.prompt("Token", hide_input=True)
    with _clean_errors():
        outcome = add_credentials(profile, token=token, token_env=token_env)
    source = f"${{{token_env}}}" if token_env else "the token you entered"
    typer.echo(f"{outcome} credentials profile '{profile}': {source}")
    typer.echo(f"written to {credentials_path()} (owner-readable only)")


@remote_app.command("add")
def remote_add(
    url: str = typer.Option(..., "--url", help="The Kyno server's URL."),
    profile: str = typer.Option("default", "--profile", help="The remote profile to write."),
    credentials: str | None = typer.Option(
        None, "--credentials", help="Take the token from this credentials profile."
    ),
    token_env: str | None = typer.Option(
        None, "--token-env", help="Take the token from this variable instead."
    ),
) -> None:
    """Add or replace one remote profile: the URL and its one token source.
    With neither --credentials nor --token-env it points at the 'default'
    credentials, which must already exist."""
    with _clean_errors():
        outcome = add_remote(url, profile, credentials_profile=credentials, token_env=token_env)
    source = f"${{{token_env}}}" if token_env else f"credentials '{credentials or 'default'}'"
    typer.echo(f"{outcome} remote profile '{profile}': {url.rstrip('/')}, token from {source}")
    typer.echo(f"written to {remotes_path()}")


@remote_app.command("show")
def remote_show(
    profile: str = typer.Option("default", "--profile", help="The remote profile to inspect."),
) -> None:
    """One profile's whole chain, token masked, and whether it resolves
    right now. Exit 1 when it doesn't, so a setup step can gate on it."""
    with _clean_errors():
        remote, failure = inspect(profile)
    typer.echo(f"profile: {remote.profile}")
    typer.echo(f"url: {remote.url}")
    typer.echo(f"token from: {remote.source}")
    if failure is None:
        typer.echo("resolves: yes")
        return
    typer.echo(f"resolves: no ({failure})")
    raise typer.Exit(code=1)


@remote_app.command("list")
def remote_list() -> None:
    """Every remote profile, one line each: name, url, token source."""
    have = remotes()
    if not have:
        typer.echo("no remote profiles; create one with: kyno remote add --url URL")
        return
    for name in sorted(have):
        remote = have[name]
        typer.echo(f"{name}  {remote.url}  token from {remote.source}")


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
        # All or nothing: a half-written export would leave the operator unsure which of the
        # files are new and which were already there.
        typer.echo(
            f"error: {target} already has {', '.join(existing)}; "
            "nothing written. Export somewhere else, or move them aside.",
            err=True,
        )
        raise typer.Exit(code=1)
    try:
        target.mkdir(parents=True, exist_ok=True)
        for name in PACKAGED_TEMPLATES:
            # "x": refuse anything that appeared since the check, including a dangling symlink
            # that exists() does not see. O_EXCL refuses to follow the symlink instead of
            # writing a file where it points.
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
    typer.echo("\nedit them, then point your workspace at your copies -- in config/server:")
    typer.echo("  [page]")
    typer.echo(f"  constitution_template = {(target / 'constitution.html').resolve()}")
    typer.echo(f"  index_template = {(target / 'index.html').resolve()}")
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
    remote: bool = typer.Option(False, "--remote", help=_REMOTE_HELP),
    profile: str = typer.Option("default", "--profile", help="Which remote profile to use."),
    credentials: str | None = typer.Option(
        None, "--credentials", help="Take the token from this credentials profile, this run."
    ),
    token_env: str | None = typer.Option(
        None, "--token-env", help="Take the token from this variable, this run."
    ),
) -> None:
    """The version in force. JSON by default; --yaml prints it as a
    constitution file, ready to redirect, commit, and re-apply."""
    _remote_options_guard(remote, profile, credentials, token_env)
    if remote:
        with _clean_errors():
            client = dial(profile, credentials_profile=credentials, token_env=token_env)
            try:
                payload = _fetch_remote_head(client, constitution)
            finally:
                client.close()
            head = version_from_payload(payload)
            if head is None:
                if as_yaml:
                    typer.echo(
                        f"error: nothing to read: '{constitution}' has no versions", err=True
                    )
                    raise typer.Exit(code=1)
                typer.echo("no constitution set (version 0)")
            elif as_yaml:
                typer.echo(render_constitution_yaml(head, constitution), nl=False)
            else:
                typer.echo(json.dumps(payload, indent=2))
        return
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
    remote: bool = typer.Option(False, "--remote", help=_REMOTE_HELP),
    profile: str = typer.Option("default", "--profile", help="Which remote profile to use."),
    credentials: str | None = typer.Option(
        None, "--credentials", help="Take the token from this credentials profile, this run."
    ),
    token_env: str | None = typer.Option(
        None, "--token-env", help="Take the token from this variable, this run."
    ),
) -> None:
    """Report how Kyno reads a file, then whether the store agrees with it.
    The field report never blocks anything. The store comparison is what a
    pipeline gates on: exit 1 when the file and the head are out of sync."""
    _remote_options_guard(remote, profile, credentials, token_env)
    try:
        report = check_constitution_file(file)
        fields = read_constitution_file(file)
    except CoherenceError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from None
    typer.echo(f"kyno fields set: {', '.join(report.present) or 'none'}")
    typer.echo(f"kyno fields not set: {', '.join(report.missing) or 'none'}")
    typer.echo(f"custom fields: {', '.join(report.custom) or 'none'}")
    if remote:
        _compare_with_remote(fields, file, profile, credentials, token_env)
    else:
        _compare_with_store(fields, file)


def _compare_with_store(fields: ConstitutionFile, path: str) -> None:
    """Say whether the store's head is what the file says. Head and delta
    come from one read, so the version named and the changes listed belong
    to the same moment. Exits 1 when they differ or nothing is there yet."""
    try:
        target = _constitution_name(fields, path)
    except AuthoringError as exc:
        typer.echo(f"store: not compared ({exc})")
        raise typer.Exit(code=1) from None
    try:
        head, delta = _control_plane().head_and_delta(**_content_of(fields), constitution=target)
    except (CoherenceError, SQLAlchemyError) as exc:
        # The cause is the first line. A database error then quotes its SQL, which tells the
        # operator nothing about the file.
        typer.echo(f"store: not compared ({str(exc).splitlines()[0]})")
        return
    _render_comparison(target, head, delta)


def _compare_with_remote(
    fields: ConstitutionFile,
    path: str,
    profile: str,
    credentials: str | None,
    token_env: str | None,
) -> None:
    """The same comparison, against a remote head. An endpoint that cannot
    be reached reads like an unreachable store: the report stands, the
    comparison says why it did not run."""
    try:
        target = _constitution_name(fields, path)
    except AuthoringError as exc:
        typer.echo(f"store: not compared ({exc})")
        raise typer.Exit(code=1) from None
    try:
        client = dial(profile, credentials_profile=credentials, token_env=token_env)
        try:
            head = version_from_payload(_fetch_remote_head(client, target))
        finally:
            client.close()
        delta = edit_delta(head, target, **_content_of(fields))
    except CoherenceError as exc:
        typer.echo(f"store: not compared ({str(exc).splitlines()[0]})")
        return
    _render_comparison(target, head, delta)


def _render_comparison(target: str, head, delta: tuple[str, ...]) -> None:
    if head is None or head.version == 0:
        typer.echo(f"store: '{target}' has no versions; applying this file creates version 1")
        raise typer.Exit(code=1)
    if not delta:
        typer.echo(f"store: agrees with '{target}' (version {head.version})")
        return
    typer.echo(f"store: differs from '{target}' (version {head.version}):")
    for line in delta:
        typer.echo(f"  {line}")
    raise typer.Exit(code=1)


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
def log(
    constitution: str = _CONSTITUTION_OPTION,
    remote: bool = typer.Option(False, "--remote", help=_REMOTE_HELP),
    profile: str = typer.Option("default", "--profile", help="Which remote profile to use."),
    credentials: str | None = typer.Option(
        None, "--credentials", help="Take the token from this credentials profile, this run."
    ),
    token_env: str | None = typer.Option(
        None, "--token-env", help="Take the token from this variable, this run."
    ),
) -> None:
    """The history, one line per version, newest first: version, date,
    author, and the change note. `kyno export` has the full content."""
    _remote_options_guard(remote, profile, credentials, token_env)
    try:
        if remote:
            rows = _fetch_remote_rows(profile, credentials, token_env, constitution)
        else:
            rows = _store().export_versions(constitution)
    except (CoherenceError, SQLAlchemyError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from None
    if not rows:
        typer.echo("no constitution set (version 0)")
        return
    for row in reversed(rows):
        day = str(row.get("created_at", ""))[:10]
        by = row.get("created_by") or "-"
        authorized_by = row.get("authorized_by") or "-"
        typer.echo(f"v{row['version']}  {day}  {by}  {authorized_by}  {row['change_note']}")


@app.command()
def export(
    from_version: int | None = typer.Option(
        None, "--from", help="First version to include (inclusive)."
    ),
    to_version: int | None = typer.Option(
        None, "--to", help="Last version to include (inclusive)."
    ),
    constitution: str = _CONSTITUTION_OPTION,
    remote: bool = typer.Option(False, "--remote", help=_REMOTE_HELP),
    profile: str = typer.Option("default", "--profile", help="Which remote profile to use."),
    credentials: str | None = typer.Option(
        None, "--credentials", help="Take the token from this credentials profile, this run."
    ),
    token_env: str | None = typer.Option(
        None, "--token-env", help="Take the token from this variable, this run."
    ),
) -> None:
    _remote_options_guard(remote, profile, credentials, token_env)
    try:
        if remote:
            rows = _fetch_remote_rows(
                profile, credentials, token_env, constitution, from_version, to_version
            )
        else:
            rows = _store().export_versions(
                constitution, from_version=from_version, to_version=to_version
            )
        typer.echo(json.dumps(rows, indent=2))
    except (CoherenceError, SQLAlchemyError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from None


@app.command("import")
def import_ledger(
    file: str = typer.Argument(..., help="A JSON file written by kyno export."),
    as_name: str = typer.Option(
        "default", "--as", help="The constitution to write the history under."
    ),
) -> None:
    """Write an exported ledger back into the database, keeping every
    version's number, date and authors. Restores a backup, or moves an
    instance into another database; --as renames the constitution on the
    way in. Local only: a replay through the server would stamp today's
    date on old history, so import writes straight to the workspace's
    database, the way `kyno db init` does."""
    try:
        rows = json.loads(Path(file).read_text())
    except OSError as exc:
        typer.echo(f"error: cannot read {file}: {exc}", err=True)
        raise typer.Exit(code=1) from None
    except json.JSONDecodeError:
        typer.echo(f"error: {file} is not a kyno export: the file is not JSON", err=True)
        raise typer.Exit(code=1) from None
    if not isinstance(rows, list):
        typer.echo(f"error: {file} is not a kyno export: expected a list of versions", err=True)
        raise typer.Exit(code=1)
    with _clean_errors():
        count = _store().import_versions(as_name, rows)
    word = "version" if count == 1 else "versions"
    typer.echo(f"imported {count} {word} into '{as_name}'")


def _fetch_remote_rows(
    profile: str,
    credentials: str | None,
    token_env: str | None,
    constitution: str,
    from_version: int | None = None,
    to_version: int | None = None,
) -> list[dict]:
    client = dial(profile, credentials_profile=credentials, token_env=token_env)
    try:
        return client.call_tool(
            "export_versions",
            {
                "constitution": constitution,
                "from_version": from_version,
                "to_version": to_version,
            },
        )
    finally:
        client.close()


@app.command()
def new(
    name: str = typer.Argument(..., help="Directory to create the workspace in."),
) -> None:
    """Create a workspace: the directory that defines one Kyno instance.
    Configuration and, on SQLite, the store live here. The constitution file
    does not: it stays in your team's repo and arrives over the wire."""
    with _clean_errors():
        root = create_workspace(Path(name))
    typer.echo(f"created workspace '{root.name}'")
    for rel in ("README.md", ".gitignore", "config/server", "db/.keep"):
        typer.echo(f"  {rel}")
    typer.echo(f"next: cd {name} && kyno db init")


@app.command()
def serve(transport: str = typer.Option("stdio", "--transport")) -> None:
    try:
        settings = Settings.load()
        store = store_from_settings(settings)
        cp = ControlPlane(store)
        if transport == "stdio":
            from kyno.serving import serve_stdio

            serve_stdio(cp)
            return
        if transport == "http":
            from kyno.serving import serve_http

            serve_http(settings, store, cp)
            return
    except CoherenceError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from None
    raise typer.BadParameter("transport must be 'stdio' or 'http'")
