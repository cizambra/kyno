# SPDX-License-Identifier: MIT
import re

from kyno.wire.errors import CoherenceError

_KEY_FORMAT = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
MAX_CONSTITUTION_KEY_CHARS = 200


def is_constitution_key(value: str) -> bool:
    """Return whether text uses lowercase letters, digits, and single hyphens."""
    return _KEY_FORMAT.fullmatch(value) is not None


def suggest_constitution_key(value: str) -> str:
    """Return a key suggestion for an error message, without changing stored identity."""
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


class InvalidConstitutionKeyError(CoherenceError, ValueError):
    """A constitution key does not satisfy the shared identifier contract."""


def check_constitution_key(value: str) -> str:
    """Trim surrounding whitespace and validate the remaining key."""
    if not isinstance(value, str):
        raise InvalidConstitutionKeyError("constitution key must be a string")
    value = value.strip()
    if len(value) > MAX_CONSTITUTION_KEY_CHARS:
        raise InvalidConstitutionKeyError(
            f"constitution key must contain at most {MAX_CONSTITUTION_KEY_CHARS} characters"
        )
    if is_constitution_key(value):
        return value
    suggestion = suggest_constitution_key(value)
    hint = f" like '{suggestion}'" if suggestion else ""
    raise InvalidConstitutionKeyError(
        f"'{value}' is not a valid constitution key: use lowercase letters and digits "
        f"with single hyphens{hint}"
    )
