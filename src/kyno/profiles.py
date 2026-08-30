"""The two client-side files behind remote mode: remotes and credentials.

Both live in the user config directory and are written only by the
commands that own them, never by hand and never next to a repo. A
remote profile is one destination: a URL and where its token comes from.
A credentials profile is one token, written in or read from a variable.
"""

from __future__ import annotations

import configparser
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from kyno.errors import ConfigError

DEFAULT_PROFILE = "default"
REMOTES_FILE = "remotes"
CREDENTIALS_FILE = "credentials"

_PROFILE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_ENV_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class ProfileError(ConfigError):
    """A profile is missing, ambiguous, or does not resolve."""


def config_dir() -> Path:
    """Where the files live: ~/.kyno, on every platform and for everyone.
    One path to remember, the same in the docs, a Dockerfile, and a
    colleague's head, the way ~/.aws and ~/.kube are."""
    return Path.home() / ".kyno"


def remotes_path() -> Path:
    return config_dir() / REMOTES_FILE


def credentials_path() -> Path:
    return config_dir() / CREDENTIALS_FILE


@dataclass(frozen=True)
class Credential:
    profile: str
    # A literal token, or a "${VAR}" reference resolved at use time.
    token: str = field(repr=False)

    @property
    def env_var(self) -> str | None:
        match = _ENV_REF.fullmatch(self.token)
        return match.group(1) if match else None


@dataclass(frozen=True)
class Remote:
    profile: str
    url: str
    # Exactly one of these is set: the profile's single token source.
    credentials: str | None = None
    token_env: str | None = None

    @property
    def source(self) -> str:
        if self.credentials is not None:
            return f"credentials '{self.credentials}'"
        return f"${{{self.token_env}}}"


@dataclass(frozen=True)
class Resolved:
    """A remote profile with its token looked up: what a client connects with."""

    profile: str
    url: str
    token: str = field(repr=False)
    chain: str


def _read(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(interpolation=None)
    if path.exists():
        parser.read(path, encoding="utf-8")
    return parser


def _write(path: Path, parser: configparser.ConfigParser, *, private: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if private:
        # Owner-readable from the first byte, not chmod'ed after the fact.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            parser.write(handle)
        os.chmod(path, 0o600)
    else:
        with path.open("w", encoding="utf-8") as handle:
            parser.write(handle)


def _check_profile_name(profile: str) -> None:
    if not _PROFILE_NAME.fullmatch(profile):
        raise ProfileError(
            f"'{profile}' is not a profile name: use letters, digits, dots, dashes, underscores"
        )


def _check_env_name(name: str) -> None:
    if not _ENV_NAME.fullmatch(name):
        raise ProfileError(f"'{name}' is not an environment variable name")


_HOST_PORT = re.compile(r"[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?(:\d{1,5})?")


def _server_url(url: str) -> bool:
    """A URL this client could actually dial: http or https, a plain
    host with an optional port and path, nothing else. Whether anything
    answers there is the connection's job, not this check's."""
    parts = urlsplit(url)
    return (
        parts.scheme in ("http", "https")
        and bool(parts.netloc)
        and "@" not in parts.netloc
        and _HOST_PORT.fullmatch(parts.netloc) is not None
        and not parts.query
        and not parts.fragment
    )


def _listing(names: list[str]) -> str:
    return ", ".join(names) if names else "none"


def credentials() -> dict[str, Credential]:
    parser = _read(credentials_path())
    return {
        name: Credential(profile=name, token=parser[name].get("token", ""))
        for name in parser.sections()
    }


def add_credentials(
    profile: str = DEFAULT_PROFILE, *, token: str | None = None, token_env: str | None = None
) -> str:
    """Write one credentials profile: the token itself, or a reference to the
    variable that holds it. Returns 'added' or 'updated'."""
    _check_profile_name(profile)
    if (token is None) == (token_env is None):
        raise ProfileError("give the token one way: --token-env VAR, or enter it at the prompt")
    if token_env is not None:
        _check_env_name(token_env)
        value = f"${{{token_env}}}"
    else:
        assert token is not None
        if not token.strip():
            raise ProfileError("a blank token was entered; nothing written")
        value = token
    parser = _read(credentials_path())
    outcome = "updated" if parser.has_section(profile) else "added"
    if outcome == "added":
        parser.add_section(profile)
    parser[profile] = {"token": value}
    _write(credentials_path(), parser, private=True)
    return outcome


def remotes() -> dict[str, Remote]:
    parser = _read(remotes_path())
    found = {}
    for name in parser.sections():
        section = parser[name]
        reference = _ENV_REF.fullmatch(section.get("token", ""))
        found[name] = Remote(
            profile=name,
            url=section.get("url", ""),
            credentials=section.get("credentials") or None,
            token_env=reference.group(1) if reference else None,
        )
    return found


def add_remote(
    url: str,
    profile: str = DEFAULT_PROFILE,
    *,
    credentials_profile: str | None = None,
    token_env: str | None = None,
) -> str:
    """Write one remote profile: the URL and its one token source. With no
    source named, it points at the 'default' credentials. Pointing at
    credentials that do not exist is refused: credentials first, then
    remotes. Returns 'added' or 'updated'."""
    _check_profile_name(profile)
    if not _server_url(url):
        raise ProfileError(
            f"'{url}' is not a server URL Kyno can dial: use http(s)://host[:port][/path]"
        )
    if credentials_profile is not None and token_env is not None:
        raise ProfileError("give the token one way: --credentials NAME, or --token-env VAR")
    if token_env is not None:
        _check_env_name(token_env)
        section = {"url": url.rstrip("/"), "token": f"${{{token_env}}}"}
    else:
        wanted = credentials_profile or DEFAULT_PROFILE
        _check_profile_name(wanted)
        have = credentials()

        if wanted not in have:
            fix = "kyno credentials add" + (
                "" if wanted == DEFAULT_PROFILE else f" --profile {wanted}"
            )
            raise ProfileError(
                f"no credentials profile '{wanted}'; "
                f"you have: {_listing(sorted(have))}. Create it with: {fix}"
            )
        section = {"url": url.rstrip("/"), "credentials": wanted}
    parser = _read(remotes_path())
    outcome = "updated" if parser.has_section(profile) else "added"
    if outcome == "added":
        parser.add_section(profile)
    parser[profile] = section
    _write(remotes_path(), parser, private=False)
    return outcome


def _token_from_env(name: str, *, owner: str) -> str:
    value = os.environ.get(name)
    if value is None:
        raise ProfileError(f"{owner} reads its token from ${{{name}}}, which is not set")
    if not value.strip():
        raise ProfileError(f"{owner} reads its token from ${{{name}}}, which is set but blank")
    return value


def _token_from_credentials(name: str, *, owner: str) -> tuple[str, str]:
    have = credentials()
    if name not in have:
        fix = "kyno credentials add" + ("" if name == DEFAULT_PROFILE else f" --profile {name}")
        raise ProfileError(
            f"{owner} points at credentials '{name}', which do not exist; "
            f"you have: {_listing(sorted(have))}. Create it with: {fix}"
        )
    credential = have[name]
    if credential.env_var is not None:
        return (
            _token_from_env(credential.env_var, owner=f"credentials '{name}'"),
            f"credentials '{name}' -> ${{{credential.env_var}}}",
        )
    if not credential.token.strip():
        raise ProfileError(f"credentials '{name}' hold no token; re-add them")
    return credential.token, f"credentials '{name}'"


def inspect(profile: str = DEFAULT_PROFILE) -> tuple[Remote, str | None]:
    """One profile's chain and whether it resolves right now: the Remote,
    and None when a token comes out, else the reason it does not. The token
    itself never comes back from here; this is for showing, not connecting."""
    have = remotes()
    if profile not in have:
        fix = "kyno remote add --url URL" + (
            "" if profile == DEFAULT_PROFILE else f" --profile {profile}"
        )
        raise ProfileError(
            f"no remote profile '{profile}'; you have: {_listing(sorted(have))}. "
            f"Create it with: {fix}"
        )
    try:
        resolve(profile)
    except ProfileError as failure:
        return have[profile], str(failure)
    return have[profile], None


def resolve(
    profile: str = DEFAULT_PROFILE,
    *,
    credentials_profile: str | None = None,
    token_env: str | None = None,
) -> Resolved:
    """Follow one chain to a URL and a token. A per-run credentials profile
    or variable swaps the token source without touching the files. Anything
    that does not resolve fails loudly, never as a fallback."""
    have = remotes()
    if profile not in have:
        fix = "kyno remote add --url URL" + (
            "" if profile == DEFAULT_PROFILE else f" --profile {profile}"
        )
        raise ProfileError(
            f"no remote profile '{profile}'; you have: {_listing(sorted(have))}. "
            f"Create it with: {fix}"
        )
    remote = have[profile]
    owner = f"remote profile '{profile}'"
    if credentials_profile is not None and token_env is not None:
        raise ProfileError("give the token one way: --credentials NAME, or --token-env VAR")
    if token_env is not None:
        _check_env_name(token_env)
        token = _token_from_env(token_env, owner="this run")
        chain = f"{profile} -> {remote.url} -> ${{{token_env}}} (this run)"
    elif credentials_profile is not None:
        token, how = _token_from_credentials(credentials_profile, owner="this run")
        chain = f"{profile} -> {remote.url} -> {how} (this run)"
    elif remote.token_env is not None:
        token = _token_from_env(remote.token_env, owner=owner)
        chain = f"{profile} -> {remote.url} -> ${{{remote.token_env}}}"
    else:
        token, how = _token_from_credentials(remote.credentials or DEFAULT_PROFILE, owner=owner)
        chain = f"{profile} -> {remote.url} -> {how}"
    return Resolved(profile=profile, url=remote.url, token=token, chain=chain)
