"""Config values: one ${VAR} reference, and coercions that name their key.

Values across Kyno's files follow one rule: a value is written in, or it
is one ${VAR} reference to a variable the operator named. This is the
resolver for that rule, plus the int/bool coercions whose refusals name
the key that went wrong -- the workspace uses them today, and the client
files' parsing can move onto them too.
"""

from __future__ import annotations

import configparser
import os
import re

from kyno.errors import ConfigError

ENV_REF = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$")


def resolve(value: str, *, owner: str, error: type[Exception] = ConfigError) -> str:
    """The value itself, or what its one ${VAR} reference points at.

    An unset or blank variable raises, naming the owner and the variable:
    a reference that silently resolves to nothing is how half-configured
    servers happen."""
    match = ENV_REF.match(value.strip())
    if match is None:
        return value.strip()
    var = match.group(1)
    got = os.environ.get(var)
    if got is None:
        raise error(f"{owner} reads ${{{var}}}, which is not set")
    if not got.strip():
        raise error(f"{owner} reads ${{{var}}}, which is blank")
    return got


def to_int(value: str, *, owner: str) -> int:
    # int() alone raises without saying which key went wrong.
    try:
        return int(value)
    except ValueError:
        raise ConfigError(f"{owner} must be an integer, got '{value}'") from None


def to_bool(value: str, *, owner: str) -> bool:
    # configparser's own truth table (true/false, 1/0, yes/no, on/off);
    # only the refusal is ours, so it names the key.
    try:
        return configparser.ConfigParser.BOOLEAN_STATES[value.lower()]
    except KeyError:
        raise ConfigError(f"{owner} must be true or false, got '{value}'") from None
