"""One ${VAR} reference, resolved.

Config values across Kyno follow one rule: a value is written in, or it
is one ${VAR} reference to a variable the operator named. This is the
resolver for that rule. The workspace uses it today, and the client files'
parsing can move onto it later.
"""

from __future__ import annotations

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
        raise error(f"{owner} reads ${{{var}}}, which is set but blank")
    return got
