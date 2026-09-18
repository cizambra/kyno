# SPDX-License-Identifier: MIT
import re

from kyno.wire.errors import CoherenceError

_SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
MAX_CONSTITUTION_KEY_CHARS = 200


class InvalidConstitutionKeyError(CoherenceError, ValueError):
    """A constitution key does not satisfy the shared identifier contract."""


def check_constitution_key(value: str | None = None) -> str:
    """Trim and validate a constitution key, resolving None to default."""
    if value is None:
        return "default"
    if not isinstance(value, str):
        raise InvalidConstitutionKeyError("constitution key must be a string")
    key = value.strip()
    if not key or len(key) > MAX_CONSTITUTION_KEY_CHARS:
        raise InvalidConstitutionKeyError("constitution key must contain 1 to 200 characters")
    if _SLUG.fullmatch(key):
        return key
    suggestion = re.sub(r"[^a-z0-9]+", "-", key.lower()).strip("-")
    hint = f" like '{suggestion}'" if suggestion else ""
    raise InvalidConstitutionKeyError(
        f"'{key}' is not a valid constitution key: use lowercase letters and digits "
        f"with single hyphens{hint}"
    )
