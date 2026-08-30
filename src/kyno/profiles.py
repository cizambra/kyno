"""The credentials file behind remote mode.

It lives in the user config directory and is written only by the command
that owns it, never by hand and never next to a repo. A credentials
profile is one token, written in or read from a variable.
"""

from __future__ import annotations

import configparser
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from kyno.errors import ConfigError

DEFAULT_PROFILE = "default"
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
